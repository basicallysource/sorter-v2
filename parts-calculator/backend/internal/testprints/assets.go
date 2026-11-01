package testprints

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os"
	"path"
	"strings"

	"connectrpc.com/connect"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

var ASSET_TYPES = map[string]string{".stl": "model/stl", ".step": "model/step", ".stp": "model/step", ".3mf": "model/3mf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

type manifest struct {
	Key         string `json:"key"`
	Namespace   string `json:"namespace"`
	Digest      string `json:"digest"`
	Size        int64  `json:"size"`
	ContentType string `json:"content_type"`
	Filename    string `json:"filename"`
	Visibility  string `json:"visibility"`
	URL         string `json:"url"`
	URLExpires  bool   `json:"url_expires"`
}

func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AssetURL == "" {
		rpcError(w, 503, "unavailable", "asset storage is not configured")
		return
	}
	select {
	case s.uploads <- struct{}{}:
		defer func() { <-s.uploads }()
	default:
		rpcError(w, 429, "resource_exhausted", "upload capacity reached")
		return
	}
	ctx := r.Context()
	test_id := r.PathValue("test_id")
	filename := r.URL.Query().Get("filename")
	if !validID(test_id) || !validText(filename, 1, 160) || path.Base(filename) != filename || strings.ContainsAny(filename, "\\\r\n") {
		rpcError(w, 400, "invalid_argument", "invalid test or filename")
		return
	}
	content_type := ASSET_TYPES[strings.ToLower(path.Ext(filename))]
	declared, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || content_type == "" || declared != content_type {
		rpcError(w, 400, "invalid_argument", "unsupported file type")
		return
	}
	test, err := readTest(ctx, s.db, test_id)
	if err != nil {
		rpcError(w, 404, "not_found", "test not found")
		return
	}
	p := actor(ctx)
	purpose := "model"
	if p.board != nil {
		purpose = "evidence"
		if !strings.HasPrefix(content_type, "image/") || boundTest(ctx, s.db, p.board, test, r.URL.Query().Get("guild_id"), r.URL.Query().Get("forum_id"), r.URL.Query().Get("thread_id")) != nil {
			rpcError(w, 403, "permission_denied", "evidence upload refused")
			return
		}
	} else if test.State != "draft" {
		rpcError(w, 409, "failed_precondition", "models can only be attached to drafts")
		return
	}
	var count int
	if err = s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM assets WHERE test_id=?", test_id).Scan(&count); err != nil || count >= 1000 {
		rpcError(w, 429, "resource_exhausted", "test asset limit reached")
		return
	}
	file, err := os.CreateTemp("", "test-print-upload-*")
	if err != nil {
		rpcError(w, 503, "unavailable", "upload unavailable")
		return
	}
	defer os.Remove(file.Name())
	defer file.Close()
	hash := sha256.New()
	size, err := io.Copy(io.MultiWriter(file, hash), http.MaxBytesReader(w, r.Body, MAX_ASSET_BYTES))
	if err != nil || size == 0 {
		rpcError(w, 413, "resource_exhausted", "empty or oversized upload")
		return
	}
	file.Seek(0, io.SeekStart)
	query := url.Values{"namespace": {s.cfg.AssetNamespace}, "filename": {filename}, "visibility": {"private"}}
	upstream, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.AssetURL+"/v1/assets?"+query.Encode(), file)
	if err != nil {
		rpcError(w, 503, "unavailable", "upload unavailable")
		return
	}
	upstream.ContentLength = size
	upstream.Header.Set("Content-Type", content_type)
	upstream.Header.Set("Authorization", "Bearer "+s.cfg.AssetToken)
	response, err := s.http.Do(upstream)
	if err != nil {
		rpcError(w, 502, "unavailable", "asset storage unavailable")
		return
	}
	defer response.Body.Close()
	var stored manifest
	if (response.StatusCode != 200 && response.StatusCode != 201) || json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&stored) != nil || !s.validManifest(stored) || stored.ContentType != content_type || stored.Filename != filename {
		rpcError(w, 502, "unavailable", "asset storage refused upload")
		return
	}
	if stored.Size != size || stored.Digest != "sha256:"+hex.EncodeToString(hash.Sum(nil)) {
		rpcError(w, 502, "unavailable", "stored bytes did not match upload")
		return
	}
	asset := &pb.Asset{Id: newID(), Filename: stored.Filename, ContentType: stored.ContentType, Size: stored.Size, Sha256: strings.TrimPrefix(stored.Digest, "sha256:")}
	body, err := protojson.Marshal(asset)
	if err != nil {
		rpcError(w, 500, "internal", "upload failed")
		return
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		rpcError(w, 503, "unavailable", "upload unavailable")
		return
	}
	defer tx.Rollback()
	// Recheck after the network call so a simultaneous publish cannot change its target.
	current, err := readTest(ctx, tx, test_id)
	if err != nil || purpose == "model" && current.State != "draft" {
		rpcError(w, 409, "failed_precondition", "test changed during upload")
		return
	}
	_, err = tx.ExecContext(ctx, "INSERT INTO assets(id,test_id,purpose,asset_key,body,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(test_id,purpose,asset_key) DO NOTHING", asset.Id, test_id, purpose, stored.Key, body, now())
	if err == nil {
		err = tx.QueryRowContext(ctx, "SELECT body FROM assets WHERE test_id=? AND purpose=? AND asset_key=?", test_id, purpose, stored.Key).Scan(&body)
	}
	if err == nil {
		err = tx.Commit()
	}
	if err != nil {
		rpcError(w, 503, "unavailable", "upload metadata unavailable; retry is safe")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(201)
	w.Write(body)
}

func (s *Server) GetDownload(ctx context.Context, req *connect.Request[pb.GetDownloadRequest]) (*connect.Response[pb.GetDownloadResponse], error) {
	if !validID(req.Msg.TestId) || !validID(req.Msg.AssetId) {
		return nil, fail(connect.CodeInvalidArgument, "invalid asset id")
	}
	test, err := readTest(ctx, s.db, req.Msg.TestId)
	if err != nil {
		return nil, err
	}
	if !s.canRead(actor(ctx), test) {
		return nil, fail(connect.CodeNotFound, "test not found")
	}
	var key, purpose string
	var body []byte
	err = s.db.QueryRowContext(ctx, "SELECT asset_key,purpose,body FROM assets WHERE test_id=? AND id=?", test.Id, req.Msg.AssetId).Scan(&key, &purpose, &body)
	if err != nil {
		return nil, fail(connect.CodeNotFound, "asset not found")
	}
	allowed := actor(ctx).who.In(ADMIN_GROUP) && purpose == "model" && test.State == "draft"
	for _, asset := range test.Assets {
		if asset.Id == req.Msg.AssetId {
			allowed = true
		}
	}
	if !allowed && purpose == "evidence" {
		var count int
		// Only evidence on visible, non-deleted feedback can be downloaded.
		err = s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM feedback,json_each(feedback.body,'$.assets') AS asset WHERE test_id=? AND deleted=0 AND json_extract(asset.value,'$.id')=?`, test.Id, req.Msg.AssetId).Scan(&count)
		if err != nil {
			return nil, err
		}
		allowed = count > 0
	}
	if !allowed {
		return nil, fail(connect.CodeNotFound, "asset not found")
	}
	if s.cfg.AssetURL == "" {
		return nil, fail(connect.CodeUnavailable, "asset storage is not configured")
	}
	upstream, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.AssetURL+"/v1/assets/"+url.PathEscape(key), nil)
	if err != nil {
		return nil, err
	}
	upstream.Header.Set("Authorization", "Bearer "+s.cfg.AssetToken)
	response, err := s.http.Do(upstream)
	if err != nil {
		return nil, fail(connect.CodeUnavailable, "asset storage unavailable")
	}
	defer response.Body.Close()
	stored := manifest{}
	if response.StatusCode != 200 || json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&stored) != nil || !s.validManifest(stored) || stored.Key != key {
		return nil, fail(connect.CodeUnavailable, "asset storage refused download")
	}
	asset := &pb.Asset{}
	if err = protojson.Unmarshal(body, asset); err != nil {
		return nil, err
	}
	if stored.Digest != "sha256:"+asset.Sha256 || stored.Size != asset.Size {
		return nil, fail(connect.CodeUnavailable, "stored asset changed")
	}
	return connect.NewResponse(&pb.GetDownloadResponse{Url: stored.URL}), nil
}

func (s *Server) validManifest(value manifest) bool {
	u, err := url.Parse(value.URL)
	return err == nil && u.Scheme+"://"+u.Host == s.cfg.StorageOrigin && u.User == nil && value.URLExpires && value.Visibility == "private" && value.Namespace == s.cfg.AssetNamespace && strings.HasPrefix(value.Key, s.cfg.AssetNamespace+"/") && path.Clean(value.Key) == value.Key && value.Size > 0 && value.Size <= MAX_ASSET_BYTES && strings.HasPrefix(value.Digest, "sha256:") && DIGEST.MatchString(strings.TrimPrefix(value.Digest, "sha256:"))
}
