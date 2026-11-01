package release

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const REPOSITORY = "basicallysource/sorter-v2"
const ARTIFACT = "parts-backend-linux-amd64.tar.gz"
const MAX_ARCHIVE = 96 << 20
const MAX_EXPANDED = 160 << 20

var TAG = regexp.MustCompile(`^parts-backend/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
var DIGEST = regexp.MustCompile(`^[a-f0-9]{64}$`)
var REVISION = regexp.MustCompile(`^[a-f0-9]{40}$`)

type Manifest struct {
	Tag      string `json:"tag"`
	Revision string `json:"revision"`
	Artifact string `json:"artifact"`
	SHA256   string `json:"sha256"`
	Schema   int    `json:"schema"`
}
type githubRelease struct {
	Tag        string `json:"tag_name"`
	Draft      bool   `json:"draft"`
	Prerelease bool   `json:"prerelease"`
}
type Config struct {
	Root           string
	AllowedSigners string
	Database       string
	HealthURL      string
}

func Update(ctx context.Context, cfg Config) error {
	u, err := url.Parse(cfg.HealthURL)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.User != nil || u.Path != "/healthz" {
		return errors.New("health URL must be loopback HTTP /healthz")
	}
	if !filepath.IsAbs(cfg.Root) || !filepath.IsAbs(cfg.Database) || !filepath.IsAbs(cfg.AllowedSigners) {
		return errors.New("release paths must be absolute")
	}
	if err = os.MkdirAll(filepath.Join(cfg.Root, "releases"), 0755); err != nil {
		return err
	}
	if err = os.Chmod(cfg.Root, 0755); err != nil {
		return err
	}
	if err = os.Chmod(filepath.Join(cfg.Root, "releases"), 0755); err != nil {
		return err
	}
	// systemd serializes the timer; a lock also protects manual invocations.
	lock, err := os.OpenFile(filepath.Join(cfg.Root, "update.lock"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return errors.New("update already running, or stale update.lock needs inspection")
	}
	lock.Close()
	defer os.Remove(lock.Name())
	client := &http.Client{Timeout: 2 * time.Minute, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || r.URL.User != nil {
			return http.ErrUseLastResponse
		}
		host := r.URL.Hostname()
		if host != "github.com" && host != "release-assets.githubusercontent.com" && host != "objects.githubusercontent.com" {
			return http.ErrUseLastResponse
		}
		return nil
	}}
	data, err := fetch(ctx, client, "https://api.github.com/repos/"+REPOSITORY+"/releases?per_page=100", 2<<20)
	if err != nil {
		return err
	}
	var releases []githubRelease
	if err = json.Unmarshal(data, &releases); err != nil {
		return err
	}
	selected := ""
	for _, candidate := range releases {
		if !candidate.Draft && !candidate.Prerelease && TAG.MatchString(candidate.Tag) && newer(candidate.Tag, selected) {
			selected = candidate.Tag
		}
	}
	if selected == "" {
		return nil
	}
	current := Manifest{}
	current_data, err := os.ReadFile(filepath.Join(cfg.Root, "current", "release.json"))
	if err == nil {
		if err = json.Unmarshal(current_data, &current); err != nil {
			return err
		}
		if !TAG.MatchString(current.Tag) {
			return errors.New("invalid installed release")
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if !newer(selected, current.Tag) {
		return nil
	}
	failed, _ := os.ReadFile(filepath.Join(cfg.Root, "failed-release"))
	if strings.TrimSpace(string(failed)) == selected {
		return errors.New("release previously failed health check; inspect before retry")
	}
	stage, err := os.MkdirTemp(cfg.Root, ".update-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	base := "https://github.com/" + REPOSITORY + "/releases/download/" + url.PathEscape(selected) + "/"
	manifest_data, err := fetch(ctx, client, base+"release.json", 64<<10)
	if err != nil {
		return err
	}
	signature, err := fetch(ctx, client, base+"release.json.sig", 16<<10)
	if err != nil {
		return err
	}
	signature_path := filepath.Join(stage, "release.json.sig")
	if err = os.WriteFile(signature_path, signature, 0600); err != nil {
		return err
	}
	if err = verify(ctx, cfg.AllowedSigners, signature_path, manifest_data); err != nil {
		return err
	}
	manifest := Manifest{}
	decoder := json.NewDecoder(bytes.NewReader(manifest_data))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&manifest); err != nil {
		return err
	}
	if manifest.Tag != selected || manifest.Artifact != ARTIFACT || !DIGEST.MatchString(manifest.SHA256) || !REVISION.MatchString(manifest.Revision) || manifest.Schema != 1 {
		return errors.New("release manifest is invalid or requires a manual schema upgrade")
	}
	archive, err := os.Create(filepath.Join(stage, "archive.tar.gz"))
	if err != nil {
		return err
	}
	defer archive.Close()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, base+ARTIFACT, nil)
	if err != nil {
		return err
	}
	response, err := client.Do(request)
	if err != nil {
		return errors.New("release download failed")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return fmt.Errorf("release download returned HTTP %d", response.StatusCode)
	}
	hash := sha256.New()
	size, err := io.Copy(io.MultiWriter(archive, hash), io.LimitReader(response.Body, MAX_ARCHIVE+1))
	if err != nil || size > MAX_ARCHIVE || hex.EncodeToString(hash.Sum(nil)) != manifest.SHA256 {
		return errors.New("release checksum or size mismatch")
	}
	if _, err = archive.Seek(0, io.SeekStart); err != nil {
		return err
	}
	install := filepath.Join(stage, "install")
	if err = extract(archive, install); err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(install, "release.json"), manifest_data, 0644); err != nil {
		return err
	}
	os.Chmod(filepath.Join(install, "release.json"), 0644)
	version := strings.TrimPrefix(selected, "parts-backend/")
	output, err := exec.CommandContext(ctx, filepath.Join(install, "parts-backend"), "-version").Output()
	if err != nil || strings.TrimSpace(string(output)) != version {
		return errors.New("binary version does not match signed release")
	}
	previous, err := os.Readlink(filepath.Join(cfg.Root, "current"))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	if previous != "" {
		if !strings.HasPrefix(previous, "releases/v") || filepath.Clean(previous) != previous || strings.Count(previous, "/") != 1 {
			return errors.New("invalid current release link")
		}
		if err = os.MkdirAll(filepath.Join(cfg.Root, "backups"), 0700); err != nil {
			return err
		}
		backup := filepath.Join(cfg.Root, "backups", time.Now().UTC().Format("20060102T150405Z")+"-"+version+".db")
		command := exec.CommandContext(ctx, filepath.Join(cfg.Root, "current", "parts-backend"), "-backup", backup)
		command.Env = append(os.Environ(), "PARTS_DATABASE="+cfg.Database)
		if output, err = command.CombinedOutput(); err != nil {
			return fmt.Errorf("database backup failed: %w", err)
		}
	}
	target := filepath.Join("releases", version)
	if _, err = os.Stat(filepath.Join(cfg.Root, target)); !os.IsNotExist(err) {
		return errors.New("release directory exists; inspect unfinished installation")
	}
	if err = os.Rename(install, filepath.Join(cfg.Root, target)); err != nil {
		return err
	}
	if err = activate(cfg.Root, target); err != nil {
		return err
	}
	err = exec.CommandContext(ctx, "systemctl", "restart", "parts-backend.service").Run()
	if err == nil {
		err = healthy(ctx, cfg.HealthURL, version)
	}
	if err != nil {
		os.WriteFile(filepath.Join(cfg.Root, "failed-release"), []byte(selected+"\n"), 0600)
		rollback_ctx, rollback_cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer rollback_cancel()
		if previous != "" && current.Schema == manifest.Schema {
			if rollback := activate(cfg.Root, previous); rollback != nil {
				return fmt.Errorf("release failed and rollback link failed: %w", rollback)
			}
			if rollback := exec.CommandContext(rollback_ctx, "systemctl", "restart", "parts-backend.service").Run(); rollback != nil {
				return fmt.Errorf("release failed and previous service could not restart: %w", rollback)
			}
			if rollback := healthy(rollback_ctx, cfg.HealthURL, strings.TrimPrefix(current.Tag, "parts-backend/")); rollback != nil {
				return fmt.Errorf("release failed and previous service is unhealthy: %w", rollback)
			}
		} else {
			exec.CommandContext(rollback_ctx, "systemctl", "stop", "parts-backend.service").Run()
		}
		return fmt.Errorf("release failed health check; previous compatible release restored when available: %w", err)
	}
	os.Remove(filepath.Join(cfg.Root, "failed-release"))
	return prune(cfg.Root, target, previous)
}

func prune(root, current, previous string) error {
	entries, err := os.ReadDir(filepath.Join(root, "releases"))
	if err != nil {
		return err
	}
	for _, entry := range entries {
		name := entry.Name()
		relative := filepath.Join("releases", name)
		if !entry.IsDir() || relative == current || relative == previous || !TAG.MatchString("parts-backend/"+name) {
			continue
		}
		data, err := os.ReadFile(filepath.Join(root, relative, "release.json"))
		if err != nil {
			return err
		}
		var manifest Manifest
		if json.Unmarshal(data, &manifest) != nil || manifest.Tag != "parts-backend/"+name {
			return errors.New("unrecognized release directory; retention stopped")
		}
		if err = os.RemoveAll(filepath.Join(root, relative)); err != nil {
			return err
		}
	}
	entries, err = os.ReadDir(filepath.Join(root, "backups"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	names := []string{}
	pattern := regexp.MustCompile(`^[0-9]{8}T[0-9]{6}Z-v[0-9]+\.[0-9]+\.[0-9]+\.db$`)
	for _, entry := range entries {
		if entry.Type().IsRegular() && pattern.MatchString(entry.Name()) {
			names = append(names, entry.Name())
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(names)))
	for i := 3; i < len(names); i++ {
		if err = os.Remove(filepath.Join(root, "backups", names[i])); err != nil {
			return err
		}
	}
	return nil
}

func fetch(ctx context.Context, client *http.Client, address string, limit int64) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	response, err := client.Do(req)
	if err != nil {
		return nil, errors.New("release metadata unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, fmt.Errorf("release metadata returned HTTP %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("release metadata exceeds limit")
	}
	return data, nil
}

func verify(ctx context.Context, signers, signature string, data []byte) error {
	command := exec.CommandContext(ctx, "ssh-keygen", "-Y", "verify", "-f", signers, "-I", "parts-backend", "-n", "parts-backend-release", "-s", signature)
	command.Stdin = bytes.NewReader(data)
	if err := command.Run(); err != nil {
		return errors.New("release signature is not trusted")
	}
	return nil
}

func newer(candidate, current string) bool {
	a := TAG.FindStringSubmatch(candidate)
	if a == nil {
		return false
	}
	b := TAG.FindStringSubmatch(current)
	if b == nil {
		return true
	}
	for i := 1; i < 4; i++ {
		x, err := strconv.ParseUint(a[i], 10, 32)
		if err != nil {
			return false
		}
		y, err := strconv.ParseUint(b[i], 10, 32)
		if err != nil {
			return false
		}
		if x != y {
			return x > y
		}
	}
	return false
}

func extract(source io.Reader, destination string) error {
	if err := os.Mkdir(destination, 0755); err != nil {
		return err
	}
	if err := os.Chmod(destination, 0755); err != nil {
		return err
	}
	zipped, err := gzip.NewReader(source)
	if err != nil {
		return err
	}
	defer zipped.Close()
	reader := tar.NewReader(zipped)
	total := int64(0)
	count := 0
	binary := false
	index := false
	seen := map[string]bool{}
	for {
		header, err := reader.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		name := strings.TrimSuffix(header.Name, "/")
		if name == "" || filepath.IsAbs(name) || filepath.Clean(name) != name || strings.Contains(name, "\\") || (name != "parts-backend" && name != "static" && !strings.HasPrefix(name, "static/")) || strings.Contains(name, "../") || seen[name] {
			return errors.New("unsafe or repeated archive path")
		}
		seen[name] = true
		count++
		total += header.Size
		if count > 4096 || header.Size < 0 || total > MAX_EXPANDED {
			return errors.New("archive exceeds limits")
		}
		path := filepath.Join(destination, name)
		if header.Typeflag == tar.TypeDir {
			if err = os.MkdirAll(path, 0755); err != nil {
				return err
			}
			os.Chmod(path, 0755)
			continue
		}
		if header.Typeflag != tar.TypeReg {
			return errors.New("archive contains a link or special file")
		}
		if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return err
		}
		file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if err != nil {
			return err
		}
		_, copy_err := io.Copy(file, reader)
		close_err := file.Close()
		if copy_err != nil {
			return copy_err
		}
		if close_err != nil {
			return close_err
		}
		mode := os.FileMode(0644)
		if name == "parts-backend" {
			mode = 0755
			binary = true
		}
		if name == "static/index.html" {
			index = true
		}
		if err = os.Chmod(path, mode); err != nil {
			return err
		}
	}
	if !binary || !index {
		return errors.New("archive lacks binary or static index")
	}
	return filepath.WalkDir(destination, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return os.Chmod(path, 0755)
		}
		return nil
	})
}

func activate(root, target string) error {
	temp := filepath.Join(root, ".current-next")
	os.Remove(temp)
	if err := os.Symlink(target, temp); err != nil {
		return err
	}
	return os.Rename(temp, filepath.Join(root, "current"))
}

func healthy(ctx context.Context, address, version string) error {
	client := &http.Client{Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	for range 15 {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
		response, err := client.Do(req)
		if err == nil {
			var result struct {
				Status  string `json:"status"`
				Version string `json:"version"`
			}
			err = json.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&result)
			response.Body.Close()
			if err == nil && response.StatusCode == 200 && result.Status == "ok" && result.Version == version {
				return nil
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Second):
		}
	}
	return errors.New("new service did not become healthy")
}
