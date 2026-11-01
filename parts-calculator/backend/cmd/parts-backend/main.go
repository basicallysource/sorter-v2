package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/basicallysource/sorter-v2/parts-calculator/backend/internal/release"
	"github.com/basicallysource/sorter-v2/parts-calculator/backend/internal/testprints"
)

var version = "dev"

func main() {
	syscall.Umask(0077)
	show_version := flag.Bool("version", false, "print version")
	backup := flag.String("backup", "", "write a consistent SQLite snapshot and exit")
	update := flag.Bool("update", false, "install the newest trusted GitHub release")
	flag.Parse()
	if *update {
		ctx, cancel := context.WithTimeout(context.Background(), 8*time.Minute)
		defer cancel()
		err := release.Update(ctx, release.Config{Root: env("PARTS_INSTALL_ROOT", "/opt/parts-backend"), AllowedSigners: env("PARTS_ALLOWED_SIGNERS", "/etc/parts-backend/allowed_signers"), Database: env("PARTS_DATABASE", "/var/lib/parts-backend/parts.db"), HealthURL: env("PARTS_HEALTH_URL", "http://127.0.0.1:8094/healthz")})
		if err != nil {
			slog.Error("update failed", "error", err)
			os.Exit(1)
		}
		return
	}
	if *show_version {
		fmt.Println(version)
		return
	}
	database := env("PARTS_DATABASE", "./data/parts.db")
	if *backup != "" {
		if err := testprints.Backup(database, *backup); err != nil {
			slog.Error("backup failed", "error", err)
			os.Exit(1)
		}
		return
	}
	if err := run(database); err != nil {
		slog.Error("service stopped", "error", err)
		os.Exit(1)
	}
}

func run(database string) error {
	if err := os.MkdirAll(filepath.Dir(database), 0700); err != nil {
		return err
	}
	key_data, err := os.ReadFile(os.Getenv("PARTS_SESSION_KEY_FILE"))
	if err != nil {
		return fmt.Errorf("read session key: %w", err)
	}
	key, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(key_data)))
	if err != nil {
		return errors.New("session key must be base64")
	}
	boards := []testprints.BoardConfig{}
	if filename := os.Getenv("PARTS_BOARDS_FILE"); filename != "" {
		file, err := os.Open(filename)
		if err != nil {
			return err
		}
		defer file.Close()
		decoder := json.NewDecoder(file)
		decoder.DisallowUnknownFields()
		if err = decoder.Decode(&boards); err != nil {
			return errors.New("invalid boards configuration")
		}
	}
	asset_token := ""
	if filename := os.Getenv("PARTS_ASSET_TOKEN_FILE"); filename != "" {
		data, err := os.ReadFile(filename)
		if err != nil {
			return err
		}
		asset_token = strings.TrimSpace(string(data))
	}
	app, err := testprints.Open(testprints.Config{Origin: os.Getenv("PARTS_ORIGIN"), IdentityURL: os.Getenv("PARTS_IDENTITY_URL"), SessionKey: key, Database: database, StaticDir: os.Getenv("PARTS_STATIC_DIR"), Boards: boards, AssetURL: os.Getenv("PARTS_ASSET_URL"), AssetToken: asset_token, AssetNamespace: os.Getenv("PARTS_ASSET_NAMESPACE"), StorageOrigin: os.Getenv("PARTS_STORAGE_ORIGIN"), Version: version})
	if err != nil {
		return err
	}
	defer app.Close()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	server := &http.Server{Addr: env("PARTS_LISTEN", "127.0.0.1:8094"), Handler: app.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 100 * time.Second, WriteTimeout: 100 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	slog.Info("parts backend started", "listen", server.Addr, "version", version)
	select {
	case err := <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		return server.Shutdown(shutdown)
	}
	return nil
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
