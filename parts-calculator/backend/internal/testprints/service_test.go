package testprints

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	rpc "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1/testprintsv1connect"
	"google.golang.org/protobuf/proto"
)

const TEST_ORIGIN = "https://parts.example"
const TEST_BOARD_TOKEN = "test-board-credential-0000000000000000000001"
const TEST_CORE_TOKEN = "test-board-credential-0000000000000000000002"
const TEST_GUILD = "100000000000000001"
const TEST_FORUM = "100000000000000002"
const TEST_THREAD = "100000000000000003"
const TEST_ACTOR = "100000000000000004"

type fixture struct {
	app    *Server
	http   *httptest.Server
	admin  rpc.AdminServiceClient
	reader rpc.TestPrintServiceClient
	board  rpc.DiscordBoardServiceClient
}

func setup(t *testing.T) fixture {
	t.Helper()
	identity := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/whoami" {
			t.Errorf("unexpected identity path %s", r.URL.Path)
		}
		token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if token == "outage" {
			w.WriteHeader(503)
			return
		}
		if token != "admin" && token != "reader" && token != "wrong-audience" {
			w.WriteHeader(401)
			return
		}
		groups := []string{}
		if token == "admin" {
			groups = append(groups, ADMIN_GROUP)
		}
		audience := TEST_ORIGIN
		if token == "wrong-audience" {
			audience = "https://other.example"
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{"account": "test-account", "handle": "tester", "groups": groups, "identities": []any{}, "token": map[string]any{"id": token, "audience": audience}})
	}))
	t.Cleanup(identity.Close)
	app, err := Open(Config{Origin: TEST_ORIGIN, IdentityURL: identity.URL, SessionKey: bytes.Repeat([]byte{3}, 32), Database: filepath.Join(t.TempDir(), "parts.db"), StaticDir: t.TempDir(), Boards: []BoardConfig{{ID: "community", Audience: "community", GuildID: TEST_GUILD, ForumID: TEST_FORUM, TokenSHA256: hashBytes([]byte(TEST_BOARD_TOKEN))}, {ID: "core", Audience: "core", GuildID: "200000000000000001", ForumID: "200000000000000002", TokenSHA256: hashBytes([]byte(TEST_CORE_TOKEN))}}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { app.Close() })
	server := httptest.NewServer(app.Handler())
	t.Cleanup(server.Close)
	return fixture{app: app, http: server, admin: rpc.NewAdminServiceClient(server.Client(), server.URL+"/rpc"), reader: rpc.NewTestPrintServiceClient(server.Client(), server.URL+"/rpc"), board: rpc.NewDiscordBoardServiceClient(server.Client(), server.URL+"/rpc")}
}

func credential[T any](message *T, token string) *connect.Request[T] {
	req := connect.NewRequest(message)
	req.Header().Set("Authorization", "Bearer "+token)
	return req
}
func checkCode(t *testing.T, err error, expected connect.Code) {
	t.Helper()
	if connect.CodeOf(err) != expected {
		t.Fatalf("got %v, want %v", err, expected)
	}
}

func createTest(t *testing.T, f fixture, board string) *pb.TestCase {
	t.Helper()
	res, err := f.admin.SaveTest(context.Background(), credential(&pb.SaveTestRequest{RequestId: newID(), Test: &pb.TestCase{Title: "Fit test", Kind: "part", State: "draft", BoardId: board, References: []*pb.OnshapeReference{{DocumentId: strings.Repeat("a", 24), VersionId: strings.Repeat("b", 24), ElementId: strings.Repeat("c", 24), PartId: "JHD"}}}}, "admin"))
	if err != nil {
		t.Fatal(err)
	}
	return res.Msg.Test
}

func publishTest(t *testing.T, f fixture, test *pb.TestCase) *pb.TestCase {
	t.Helper()
	test = proto.Clone(test).(*pb.TestCase)
	test.State = "open"
	res, err := f.admin.SaveTest(context.Background(), credential(&pb.SaveTestRequest{RequestId: newID(), Test: test, ExpectedRevision: test.Revision}, "admin"))
	if err != nil {
		t.Fatal(err)
	}
	return res.Msg.Test
}

func TestAuthorizationAndIsolation(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	for _, token := range []string{"reader", "wrong-audience", "outage", TEST_BOARD_TOKEN} {
		_, err := f.admin.ListBoards(ctx, credential(&pb.ListBoardsRequest{}, token))
		want := connect.CodeUnauthenticated
		if token == "reader" {
			want = connect.CodePermissionDenied
		}
		if token == "outage" {
			want = connect.CodeUnavailable
		}
		checkCode(t, err, want)
	}
	req := connect.NewRequest(&pb.ListTestsRequest{})
	req.Header().Set("Origin", "https://evil.example")
	_, err := f.reader.ListTests(ctx, req)
	checkCode(t, err, connect.CodePermissionDenied)
	public := createTest(t, f, "community")
	private := publishTest(t, f, createTest(t, f, "core"))
	for _, id := range []string{public.Id, private.Id} {
		_, err = f.reader.GetTest(ctx, credential(&pb.GetTestRequest{Id: id}, "reader"))
		checkCode(t, err, connect.CodeNotFound)
	}
	feed, err := f.board.SyncChanges(ctx, credential(&pb.SyncChangesRequest{}, TEST_BOARD_TOKEN))
	if err != nil || len(feed.Msg.Changes) != 0 {
		t.Fatalf("draft or Core leak: %v %v", feed, err)
	}
	public = publishTest(t, f, public)
	feed, err = f.board.SyncChanges(ctx, credential(&pb.SyncChangesRequest{}, TEST_BOARD_TOKEN))
	if err != nil || len(feed.Msg.Changes) != 1 || feed.Msg.Changes[0].Test.Id != public.Id {
		t.Fatalf("wrong feed: %v %v", feed, err)
	}
	_, err = f.board.BindThread(ctx, credential(&pb.BindThreadRequest{TestId: private.Id, GuildId: TEST_GUILD, ForumId: TEST_FORUM, ThreadId: TEST_THREAD}, TEST_BOARD_TOKEN))
	checkCode(t, err, connect.CodeNotFound)
	list, err := f.reader.ListTests(ctx, credential(&pb.ListTestsRequest{IncludeDrafts: true}, "reader"))
	if err != nil || len(list.Msg.Tests) != 1 {
		t.Fatalf("wrong list: %v %v", list, err)
	}
}

func TestRetryAndImmutableTarget(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	test := createTest(t, f, "community")
	request := &pb.SaveTestRequest{RequestId: newID(), Test: test, ExpectedRevision: test.Revision}
	request.Test.State = "open"
	first, err := f.admin.SaveTest(ctx, credential(request, "admin"))
	if err != nil {
		t.Fatal(err)
	}
	var workers sync.WaitGroup
	for range 4 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			res, err := f.admin.SaveTest(ctx, credential(request, "admin"))
			if err != nil || !proto.Equal(res.Msg.Test, first.Msg.Test) {
				t.Errorf("retry: %v %v", res, err)
			}
		}()
	}
	workers.Wait()
	request.Test.Title = "changed"
	_, err = f.admin.SaveTest(ctx, credential(request, "admin"))
	checkCode(t, err, connect.CodeAlreadyExists)
	request.RequestId = newID()
	_, err = f.admin.SaveTest(ctx, credential(request, "admin"))
	checkCode(t, err, connect.CodeAborted)
	request.Test = first.Msg.Test
	request.ExpectedRevision = first.Msg.Test.Revision
	request.Test.References[0].VersionId = strings.Repeat("d", 24)
	_, err = f.admin.SaveTest(ctx, credential(request, "admin"))
	checkCode(t, err, connect.CodeFailedPrecondition)
	feed, err := f.board.SyncChanges(ctx, credential(&pb.SyncChangesRequest{}, TEST_BOARD_TOKEN))
	if err != nil || len(feed.Msg.Changes) != 1 {
		t.Fatalf("duplicate feed entries: %v %v", feed, err)
	}
}

func TestEventsSurviveRetriesAndReordering(t *testing.T) {
	f := setup(t)
	ctx := context.Background()
	test := publishTest(t, f, createTest(t, f, "community"))
	event := &pb.ApplyEventRequest{TestId: test.Id, GuildId: TEST_GUILD, ForumId: TEST_FORUM, ThreadId: TEST_THREAD, MessageId: "100000000000000005", ActorId: TEST_ACTOR, DisplayName: "Tester", Kind: "claim", OccurredAt: time.Now().Add(-time.Minute).Format(time.RFC3339Nano)}
	apply := func() (*connect.Response[pb.ApplyEventResponse], error) {
		data, _ := proto.Marshal(event)
		event.EventId = hashBytes(data)
		return f.board.ApplyEvent(ctx, credential(event, TEST_BOARD_TOKEN))
	}
	_, err := apply()
	checkCode(t, err, connect.CodePermissionDenied)
	_, err = f.board.BindThread(ctx, credential(&pb.BindThreadRequest{TestId: test.Id, GuildId: TEST_GUILD, ForumId: TEST_FORUM, ThreadId: TEST_THREAD}, TEST_BOARD_TOKEN))
	if err != nil {
		t.Fatal(err)
	}
	_, err = apply()
	if err != nil {
		t.Fatal(err)
	}
	duplicate, err := f.board.ApplyEvent(ctx, credential(event, TEST_BOARD_TOKEN))
	if err != nil || !duplicate.Msg.Duplicate {
		t.Fatalf("duplicate: %v %v", duplicate, err)
	}
	event.Kind = "release"
	event.OccurredAt = time.Now().Format(time.RFC3339Nano)
	if _, err = apply(); err != nil {
		t.Fatal(err)
	}
	event.Kind = "claim"
	event.OccurredAt = time.Now().Add(-30 * time.Second).Format(time.RFC3339Nano)
	res, err := apply()
	if err != nil || !res.Msg.Ignored {
		t.Fatalf("stale claim: %v %v", res, err)
	}
	event.Kind = "feedback"
	event.Body = "Fits"
	event.OccurredAt = time.Now().Format(time.RFC3339Nano)
	if _, err = apply(); err != nil {
		t.Fatal(err)
	}
	event.Kind = "delete_feedback"
	event.Body = ""
	event.OccurredAt = time.Now().Format(time.RFC3339Nano)
	if _, err = apply(); err != nil {
		t.Fatal(err)
	}
	event.Kind = "feedback"
	event.Body = "Delayed edit"
	event.OccurredAt = time.Now().Add(time.Second).Format(time.RFC3339Nano)
	res, err = apply()
	if err != nil || !res.Msg.Ignored {
		t.Fatalf("resurrection: %v %v", res, err)
	}
	view, err := f.reader.GetTest(ctx, credential(&pb.GetTestRequest{Id: test.Id}, "reader"))
	if err != nil || view.Msg.Test.ClaimCount != 0 || view.Msg.Test.FeedbackCount != 0 || len(view.Msg.Feedback) != 0 {
		t.Fatalf("unexpected view: %v %v", view, err)
	}
	backup := filepath.Join(t.TempDir(), "snapshot.db")
	if err = Backup(f.app.cfg.Database, backup); err != nil {
		t.Fatal(err)
	}
	db, err := openDatabase(backup)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	stored, err := readTest(ctx, db, test.Id)
	if err != nil || stored.Revision != view.Msg.Test.Revision {
		t.Fatalf("backup did not preserve state: %v", err)
	}
}

func TestAssetStorageIsPrivateAndBound(t *testing.T) {
	f := setup(t)
	test := createTest(t, f, "community")
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("x", 32) || r.URL.Query().Get("visibility") != "private" {
			t.Error("upload did not use scoped private storage")
		}
		body, _ := io.ReadAll(r.Body)
		if string(body) != "model bytes" {
			t.Errorf("body %q", body)
		}
		json.NewEncoder(w).Encode(manifest{Key: "tests/model.step", Namespace: "tests", Digest: "sha256:" + hashBytes(body), Size: int64(len(body)), ContentType: "model/step", Filename: "model.step", Visibility: "private", URL: "https://storage.example/tests/model.step?signature=test", URLExpires: true})
	}))
	defer storage.Close()
	f.app.cfg.AssetURL = storage.URL
	f.app.cfg.AssetToken = strings.Repeat("x", 32)
	f.app.cfg.AssetNamespace = "tests"
	f.app.cfg.StorageOrigin = "https://storage.example"
	request, _ := http.NewRequest(http.MethodPost, f.http.URL+"/api/test-print-assets/"+test.Id+"?filename=model.step", strings.NewReader("model bytes"))
	request.Header.Set("Authorization", "Bearer admin")
	request.Header.Set("Content-Type", "model/step")
	response, err := f.http.Client().Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != 201 {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("upload: %d %s", response.StatusCode, body)
	}
	var asset struct {
		ID string `json:"id"`
	}
	if err = json.NewDecoder(response.Body).Decode(&asset); err != nil {
		t.Fatal(err)
	}
	other := createTest(t, f, "community")
	other.Assets = []*pb.Asset{{Id: asset.ID}}
	_, err = f.admin.SaveTest(context.Background(), credential(&pb.SaveTestRequest{RequestId: newID(), Test: other, ExpectedRevision: other.Revision}, "admin"))
	checkCode(t, err, connect.CodeInvalidArgument)
}
