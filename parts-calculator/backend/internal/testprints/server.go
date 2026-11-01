package testprints

import (
	"context"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/basicallysource/identity/client"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	rpc "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1/testprintsv1connect"
)

type principal struct {
	who   client.Who
	board *BoardConfig
}
type principalKey struct{}

type Server struct {
	cfg      Config
	db       *sql.DB
	auth     *client.Auth
	http     *http.Client
	boards   map[string]BoardConfig
	uploads  chan struct{}
	requests chan struct{}
	handler  http.Handler
}

func Open(cfg Config) (*Server, error) {
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}
	cookie := "parts-session"
	if strings.HasPrefix(cfg.Origin, "https://") {
		cookie = "__Host-parts-session"
	}
	auth, err := client.New(client.Config{IdentityURL: cfg.IdentityURL, BaseURL: cfg.Origin, Key: cfg.SessionKey, Cookie: cookie, Recheck: time.Minute})
	if err != nil {
		return nil, err
	}
	db, err := openDatabase(cfg.Database)
	if err != nil {
		return nil, err
	}
	for _, board := range cfg.Boards {
		_, err = db.Exec("INSERT INTO boards(id,audience,guild_id,forum_id) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING", board.ID, board.Audience, board.GuildID, board.ForumID)
		if err != nil {
			db.Close()
			return nil, err
		}
		var audience, guild, forum string
		err = db.QueryRow("SELECT audience,guild_id,forum_id FROM boards WHERE id=?", board.ID).Scan(&audience, &guild, &forum)
		if err != nil || audience != board.Audience || guild != board.GuildID || forum != board.ForumID {
			db.Close()
			return nil, errors.New("stored board identity changed; use a new board id")
		}
	}
	s := &Server{cfg: cfg, db: db, auth: auth, boards: map[string]BoardConfig{}, uploads: make(chan struct{}, 2), requests: make(chan struct{}, 32), http: &http.Client{Timeout: 60 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	for _, board := range cfg.Boards {
		s.boards[board.ID] = board
	}
	mux := http.NewServeMux()
	auth.Routes(mux)
	options := []connect.HandlerOption{connect.WithReadMaxBytes(MAX_RPC_BYTES), connect.WithSendMaxBytes(4 << 20), connect.WithInterceptors(connect.UnaryInterceptorFunc(s.safeErrors))}
	path, handler := rpc.NewTestPrintServiceHandler(s, options...)
	mux.Handle("/rpc"+path, s.authorize("reader", http.StripPrefix("/rpc", handler)))
	path, handler = rpc.NewAdminServiceHandler(s, options...)
	mux.Handle("/rpc"+path, s.authorize("admin", http.StripPrefix("/rpc", handler)))
	path, handler = rpc.NewDiscordBoardServiceHandler(s, options...)
	mux.Handle("/rpc"+path, s.authorize("board", http.StripPrefix("/rpc", handler)))
	mux.Handle("POST /api/test-print-assets/{test_id}", s.authorize("upload", http.HandlerFunc(s.upload)))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		if err := db.PingContext(r.Context()); err != nil {
			http.Error(w, "unavailable", 503)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok", "version": cfg.Version})
	})
	if cfg.StaticDir != "" {
		files := http.FileServer(http.Dir(cfg.StaticDir))
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodGet && r.Method != http.MethodHead {
				http.Error(w, "method not allowed", 405)
				return
			}
			if strings.HasPrefix(r.URL.Path, "/rpc/") || strings.HasPrefix(r.URL.Path, "/auth/") || strings.HasPrefix(r.URL.Path, "/api/test-print-assets") {
				http.NotFound(w, r)
				return
			}
			if r.URL.Path == "/admin" || r.URL.Path == "/admin.html" {
				who, err := auth.Check(r)
				if errors.Is(err, client.ErrUnavailable) {
					http.Error(w, "sign-in unavailable", 503)
					return
				}
				if err != nil {
					http.Redirect(w, r, auth.SignInURL("/admin"), http.StatusSeeOther)
					return
				}
				if !who.In(ADMIN_GROUP) {
					http.Error(w, "access denied", 403)
					return
				}
			}
			// FileServer cleans paths again; no files outside the static root are served.
			if filepath.Ext(r.URL.Path) == "" && r.URL.Path != "/" {
				clean := filepath.Join(cfg.StaticDir, filepath.FromSlash(strings.TrimPrefix(filepath.Clean("/"+r.URL.Path), "/"))+".html")
				if info, err := os.Stat(clean); err == nil && !info.IsDir() {
					r = r.Clone(r.Context())
					r.URL.Path += ".html"
				}
			}
			files.ServeHTTP(w, r)
		})
	}
	s.handler = s.headers(mux)
	return s, nil
}

func (s *Server) Handler() http.Handler { return s.handler }
func (s *Server) Close() error          { return s.db.Close() }

func (s *Server) headers(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "same-origin")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Cache-Control", "no-store")
		if strings.HasPrefix(r.URL.Path, "/admin") || strings.HasPrefix(r.URL.Path, "/test-prints") {
			w.Header().Set("X-Robots-Tag", "noindex, nofollow")
		}
		select {
		case s.requests <- struct{}{}:
			defer func() { <-s.requests }()
		default:
			http.Error(w, "busy; retry shortly", 503)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) authorize(role string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			rpcError(w, 405, "unimplemented", "POST required")
			return
		}
		origin := r.Header.Get("Origin")
		bearer := r.Header.Get("Authorization")
		if origin != "" && origin != s.cfg.Origin {
			rpcError(w, 403, "permission_denied", "origin refused")
			return
		}
		if bearer == "" && origin != s.cfg.Origin {
			rpcError(w, 403, "permission_denied", "same-origin request required")
			return
		}
		if bearer != "" && (!strings.HasPrefix(bearer, "Bearer ") || r.Header.Get("Cookie") != "") {
			rpcError(w, 401, "unauthenticated", "use one credential")
			return
		}
		p := principal{}
		if role == "board" || role == "upload" {
			p.board = s.boardFor(strings.TrimPrefix(bearer, "Bearer "))
		}
		if role == "board" && p.board == nil {
			rpcError(w, 401, "unauthenticated", "board credential required")
			return
		}
		if p.board == nil {
			var err error
			if bearer != "" {
				p.who, err = s.auth.WhoToken(r.Context(), strings.TrimPrefix(bearer, "Bearer "))
			} else {
				p.who, err = s.auth.Check(r)
			}
			if errors.Is(err, client.ErrUnavailable) {
				rpcError(w, 503, "unavailable", "sign-in unavailable")
				return
			}
			is_session := r.URL.Path == "/rpc/testprints.v1.TestPrintService/GetSession"
			if err != nil && !is_session {
				rpcError(w, 401, "unauthenticated", "sign in required")
				return
			}
			if (role == "admin" || role == "upload") && !p.who.In(ADMIN_GROUP) {
				rpcError(w, 403, "permission_denied", "administrator access required")
				return
			}
		}
		timeout := 15 * time.Second
		if role == "upload" {
			timeout = 90 * time.Second
		} else {
			r.Body = http.MaxBytesReader(w, r.Body, MAX_RPC_BYTES)
		}
		ctx, cancel := context.WithTimeout(context.WithValue(r.Context(), principalKey{}, p), timeout)
		defer cancel()
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (s *Server) boardFor(token string) *BoardConfig {
	if len(token) < 32 || len(token) > 256 {
		return nil
	}
	digest, _ := hex.DecodeString(hashBytes([]byte(token)))
	for _, board := range s.boards {
		expected, _ := hex.DecodeString(board.TokenSHA256)
		if subtle.ConstantTimeCompare(digest, expected) == 1 {
			return &board
		}
	}
	return nil
}

func (s *Server) safeErrors(next connect.UnaryFunc) connect.UnaryFunc {
	return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		response, err := next(ctx, req)
		var rpc_err *connect.Error
		if err != nil && !errors.As(err, &rpc_err) {
			slog.Error("RPC failed", "procedure", req.Spec().Procedure, "error", err)
			return nil, fail(connect.CodeInternal, "request failed")
		}
		return response, err
	}
}

func rpcError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"code": code, "message": message})
}

func actor(ctx context.Context) principal { p, _ := ctx.Value(principalKey{}).(principal); return p }

func (s *Server) canRead(p principal, test *pb.TestCase) bool {
	board, exists := s.boards[test.BoardId]
	return exists && (p.who.In(ADMIN_GROUP) || (p.who.Account != "" && board.Audience == "community" && test.State != "draft"))
}
