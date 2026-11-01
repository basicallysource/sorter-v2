package release

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func archive(t *testing.T, entries map[string]string, link string) []byte {
	t.Helper()
	var data bytes.Buffer
	zip := gzip.NewWriter(&data)
	writer := tar.NewWriter(zip)
	for name, body := range entries {
		if err := writer.WriteHeader(&tar.Header{Name: name, Mode: 0644, Size: int64(len(body)), Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		writer.Write([]byte(body))
	}
	if link != "" {
		writer.WriteHeader(&tar.Header{Name: link, Mode: 0777, Typeflag: tar.TypeSymlink, Linkname: "/etc/passwd"})
	}
	writer.Close()
	zip.Close()
	return data.Bytes()
}

func TestArchiveBoundary(t *testing.T) {
	good := map[string]string{"parts-backend": "binary", "static/index.html": "page", "static/_app/main.js": "script"}
	for _, bad := range []string{"../escape", "static/../../escape", "/etc/passwd", "static/../escape", "parts-backend/child"} {
		entries := map[string]string{}
		for key, value := range good {
			entries[key] = value
		}
		entries[bad] = "bad"
		if err := extract(bytes.NewReader(archive(t, entries, "")), filepath.Join(t.TempDir(), "install")); err == nil {
			t.Fatalf("accepted %s", bad)
		}
	}
	if err := extract(bytes.NewReader(archive(t, good, "static/link")), filepath.Join(t.TempDir(), "install")); err == nil {
		t.Fatal("accepted symlink")
	}
	if err := extract(bytes.NewReader(archive(t, good, "")), filepath.Join(t.TempDir(), "install")); err != nil {
		t.Fatal(err)
	}
}

func TestReleaseOrdering(t *testing.T) {
	for _, pair := range [][2]string{{"parts-backend/v1.2.10", "parts-backend/v1.2.9"}, {"parts-backend/v2.0.0", "parts-backend/v1.99.99"}} {
		if !newer(pair[0], pair[1]) || newer(pair[1], pair[0]) {
			t.Fatal(pair)
		}
	}
	for _, tag := range []string{"hive/v999.0.0", "parts-backend/v1.0.0-rc1", "parts-backend/v01.2.3"} {
		if newer(tag, "") {
			t.Fatalf("accepted %s", tag)
		}
	}
}

func TestSignedUpdateAndRollback(t *testing.T) {
	for _, scenario := range []string{"success", "tampered", "health-failure"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			key := filepath.Join(root, "signer")
			if output, err := exec.Command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key).CombinedOutput(); err != nil {
				t.Fatalf("key: %v %s", err, output)
			}
			pub, _ := os.ReadFile(key + ".pub")
			signers := filepath.Join(root, "allowed_signers")
			os.WriteFile(signers, append([]byte("parts-backend "), pub...), 0600)
			binary := "#!/bin/sh\nif [ \"$1\" = -version ]; then echo v1.0.1; else echo snapshot > \"$2\"; fi\n"
			package_data := archive(t, map[string]string{"parts-backend": binary, "static/index.html": "page"}, "")
			hash := sha256.Sum256(package_data)
			manifest := Manifest{Tag: "parts-backend/v1.0.1", Revision: strings.Repeat("a", 40), Artifact: ARTIFACT, SHA256: hex.EncodeToString(hash[:]), Schema: 1}
			data, _ := json.Marshal(manifest)
			manifest_file := filepath.Join(root, "release.json")
			os.WriteFile(manifest_file, data, 0600)
			if output, err := exec.Command("ssh-keygen", "-Y", "sign", "-f", key, "-n", "parts-backend-release", manifest_file).CombinedOutput(); err != nil {
				t.Fatalf("sign: %v %s", err, output)
			}
			signature, _ := os.ReadFile(manifest_file + ".sig")
			if scenario == "tampered" {
				data = append(data, ' ')
			}
			prior := filepath.Join(root, "releases", "v1.0.0")
			os.MkdirAll(prior, 0755)
			old := manifest
			old.Tag = "parts-backend/v1.0.0"
			old_data, _ := json.Marshal(old)
			os.WriteFile(filepath.Join(prior, "release.json"), old_data, 0644)
			os.WriteFile(filepath.Join(prior, "parts-backend"), []byte(binary), 0755)
			os.Symlink("releases/v1.0.0", filepath.Join(root, "current"))
			bin := filepath.Join(root, "commands")
			os.Mkdir(bin, 0755)
			os.WriteFile(filepath.Join(bin, "systemctl"), []byte("#!/bin/sh\nexit 0\n"), 0755)
			t.Setenv("PATH", bin+":"+os.Getenv("PATH"))
			health := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				link, _ := os.Readlink(filepath.Join(root, "current"))
				version := filepath.Base(link)
				if scenario == "health-failure" {
					version = "v1.0.0"
				}
				json.NewEncoder(w).Encode(map[string]string{"status": "ok", "version": version})
			}))
			defer health.Close()
			original := http.DefaultTransport
			http.DefaultTransport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.URL.Hostname() == "127.0.0.1" {
					return original.RoundTrip(r)
				}
				body := []byte{}
				status := 200
				switch {
				case r.URL.Host == "api.github.com":
					body = []byte(`[{"tag_name":"parts-backend/v1.0.1","draft":false,"prerelease":false}]`)
				case strings.HasSuffix(r.URL.Path, "release.json.sig"):
					body = signature
				case strings.HasSuffix(r.URL.Path, "release.json"):
					body = data
				case strings.HasSuffix(r.URL.Path, ARTIFACT):
					body = package_data
				default:
					status = 404
				}
				return &http.Response{StatusCode: status, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header), Request: r}, nil
			})
			defer func() { http.DefaultTransport = original }()
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			cfg := Config{Root: root, AllowedSigners: signers, Database: filepath.Join(root, "data.db"), HealthURL: health.URL + "/healthz"}
			err := Update(ctx, cfg)
			if (err == nil) != (scenario == "success") {
				t.Fatalf("update result: %v", err)
			}
			link, _ := os.Readlink(filepath.Join(root, "current"))
			expected := "releases/v1.0.0"
			if scenario == "success" {
				expected = "releases/v1.0.1"
			}
			if link != expected {
				t.Fatalf("current=%s want=%s", link, expected)
			}
			if scenario == "success" {
				if err = Update(context.Background(), cfg); err != nil {
					t.Fatalf("idempotent update: %v", err)
				}
			}
			if scenario == "health-failure" {
				failed, _ := os.ReadFile(filepath.Join(root, "failed-release"))
				if strings.TrimSpace(string(failed)) != manifest.Tag {
					t.Fatal("failed release was not quarantined")
				}
			}
		})
	}
}
