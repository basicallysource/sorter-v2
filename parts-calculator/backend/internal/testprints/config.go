package testprints

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net"
	"net/url"
	"regexp"
	"strings"
)

const ADMIN_GROUP = "basically-core"
const MAX_RPC_BYTES = 256 << 10
const MAX_ASSET_BYTES = 32 << 20
const MAX_PAGE = 100

var NAME = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,47}$`)
var SNOWFLAKE = regexp.MustCompile(`^[1-9][0-9]{16,19}$`)
var ONSHAPE_ID = regexp.MustCompile(`^[a-f0-9]{24}$`)
var DIGEST = regexp.MustCompile(`^[a-f0-9]{64}$`)

type BoardConfig struct {
	ID          string `json:"id"`
	Audience    string `json:"audience"`
	GuildID     string `json:"guild_id"`
	ForumID     string `json:"forum_id"`
	TokenSHA256 string `json:"token_sha256"`
}

type Config struct {
	Origin         string
	IdentityURL    string
	SessionKey     []byte
	Database       string
	StaticDir      string
	Boards         []BoardConfig
	AssetURL       string
	AssetToken     string
	AssetNamespace string
	StorageOrigin  string
	Version        string
}

func validateConfig(cfg Config) error {
	if !validOrigin(cfg.Origin) || !validOrigin(cfg.IdentityURL) {
		return errors.New("site and identity origins must be HTTPS, or HTTP loopback")
	}
	if len(cfg.SessionKey) != 32 {
		return errors.New("session key must contain 32 bytes")
	}
	if cfg.Database == "" {
		return errors.New("database path is required")
	}
	ids, forums, tokens := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, board := range cfg.Boards {
		if !NAME.MatchString(board.ID) || (board.Audience != "community" && board.Audience != "core") || !SNOWFLAKE.MatchString(board.GuildID) || !SNOWFLAKE.MatchString(board.ForumID) || !DIGEST.MatchString(board.TokenSHA256) {
			return errors.New("invalid board configuration")
		}
		if ids[board.ID] || forums[board.ForumID] || tokens[board.TokenSHA256] {
			return errors.New("boards must have distinct ids, forums and credentials")
		}
		ids[board.ID], forums[board.ForumID], tokens[board.TokenSHA256] = true, true, true
	}
	if cfg.AssetURL != "" || cfg.AssetToken != "" || cfg.AssetNamespace != "" || cfg.StorageOrigin != "" {
		if !validOrigin(cfg.AssetURL) || len(cfg.AssetToken) < 32 || !NAME.MatchString(cfg.AssetNamespace) || !validOrigin(cfg.StorageOrigin) {
			return errors.New("asset storage requires an origin, scoped credential, namespace and storage origin")
		}
	}
	return nil
}

func validOrigin(value string) bool {
	u, err := url.Parse(value)
	if err != nil || u.User != nil || u.Host == "" || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || strings.ToLower(u.Host) != u.Host {
		return false
	}
	return u.Scheme == "https" || (u.Scheme == "http" && (u.Hostname() == "localhost" || net.ParseIP(u.Hostname()).IsLoopback()))
}

func hashBytes(body []byte) string {
	digest := sha256.Sum256(body)
	return hex.EncodeToString(digest[:])
}
