package testprints

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"time"

	"connectrpc.com/connect"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	"github.com/google/uuid"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	_ "modernc.org/sqlite"
)

const SCHEMA_VERSION = 1
const SCHEMA = `
CREATE TABLE boards (id TEXT PRIMARY KEY, audience TEXT NOT NULL, guild_id TEXT NOT NULL, forum_id TEXT NOT NULL);
CREATE TABLE tests (
 id TEXT PRIMARY KEY, board_id TEXT NOT NULL, state TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision > 0), body BLOB NOT NULL
);
CREATE INDEX tests_board ON tests(board_id, state, id);
CREATE TABLE changes (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, board_id TEXT NOT NULL,
 test_id TEXT NOT NULL REFERENCES tests(id), body BLOB NOT NULL
);
CREATE INDEX changes_board ON changes(board_id, sequence);
CREATE TABLE receipts (
 scope TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL, result BLOB NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(scope, id)
);
CREATE TABLE bindings (
 test_id TEXT PRIMARY KEY REFERENCES tests(id), board_id TEXT NOT NULL,
 thread_id TEXT NOT NULL UNIQUE
);
CREATE TABLE claims (
 test_id TEXT NOT NULL REFERENCES tests(id), actor_id TEXT NOT NULL,
 display_name TEXT NOT NULL, created_at TEXT NOT NULL, changed_at TEXT NOT NULL,
 active INTEGER NOT NULL, PRIMARY KEY(test_id, actor_id)
);
CREATE TABLE feedback (
 id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES tests(id), message_id TEXT NOT NULL,
 actor_id TEXT NOT NULL, body BLOB NOT NULL, changed_at TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0, UNIQUE(test_id, message_id)
);
CREATE INDEX feedback_test ON feedback(test_id, deleted, id);
CREATE TABLE assets (
 id TEXT PRIMARY KEY, test_id TEXT NOT NULL REFERENCES tests(id), purpose TEXT NOT NULL,
 asset_key TEXT NOT NULL, body BLOB NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(test_id, purpose, asset_key)
);
CREATE TABLE audit (
 id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
 test_id TEXT NOT NULL, created_at TEXT NOT NULL
);
PRAGMA user_version = 1;
`

type queryer interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

func openDatabase(path string) (*sql.DB, error) {
	path, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	dsn := (&url.URL{Scheme: "file", Path: path}).String() + "?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)&_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	var version int
	if err = db.QueryRow("PRAGMA user_version").Scan(&version); err == nil && version > SCHEMA_VERSION {
		err = fmt.Errorf("database schema %d is newer than this binary", version)
	}
	if err == nil && version == 0 {
		var tx *sql.Tx
		tx, err = db.Begin()
		if err == nil {
			if _, err = tx.Exec(SCHEMA); err == nil {
				err = tx.Commit()
			} else {
				tx.Rollback()
			}
		}
	}
	if err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func readTest(ctx context.Context, db queryer, id string) (*pb.TestCase, error) {
	var body []byte
	if err := db.QueryRowContext(ctx, "SELECT body FROM tests WHERE id = ?", id).Scan(&body); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, fail(connect.CodeNotFound, "test not found")
		}
		return nil, err
	}
	test := &pb.TestCase{}
	return test, protojson.Unmarshal(body, test)
}

func writeTest(ctx context.Context, tx *sql.Tx, test *pb.TestCase, publish bool) error {
	body, err := protojson.Marshal(test)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO tests(id,board_id,state,revision,body) VALUES(?,?,?,?,?)
 ON CONFLICT(id) DO UPDATE SET board_id=excluded.board_id,state=excluded.state,revision=excluded.revision,body=excluded.body`,
		test.Id, test.BoardId, test.State, test.Revision, body)
	if err == nil && publish {
		_, err = tx.ExecContext(ctx, "INSERT INTO changes(board_id,test_id,body) VALUES(?,?,?)", test.BoardId, test.Id, body)
	}
	return err
}

func receipt(ctx context.Context, tx *sql.Tx, scope, id, digest string, result proto.Message) (bool, error) {
	var stored_digest string
	var body []byte
	err := tx.QueryRowContext(ctx, "SELECT digest,result FROM receipts WHERE scope=? AND id=?", scope, id).Scan(&stored_digest, &body)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if stored_digest != digest {
		return false, fail(connect.CodeAlreadyExists, "request id was already used for different content")
	}
	return true, protojson.Unmarshal(body, result)
}

func saveReceipt(ctx context.Context, tx *sql.Tx, scope, id, digest string, result proto.Message) error {
	body, err := protojson.Marshal(result)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, "INSERT INTO receipts(scope,id,digest,result,created_at) VALUES(?,?,?,?,?)", scope, id, digest, body, now())
	return err
}

func audit(ctx context.Context, tx *sql.Tx, actor, action, test_id string) error {
	_, err := tx.ExecContext(ctx, "INSERT INTO audit(id,actor,action,test_id,created_at) VALUES(?,?,?,?,?)", newID(), actor, action, test_id, now())
	return err
}

func newID() string { return uuid.Must(uuid.NewV7()).String() }
func now() string   { return time.Now().UTC().Format(time.RFC3339Nano) }
func fail(code connect.Code, message string) error {
	return connect.NewError(code, errors.New(message))
}

func Backup(source, destination string) error {
	if _, err := os.Stat(source); err != nil {
		return err
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		return errors.New("backup destination must not exist")
	}
	db, err := openDatabase(source)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec("VACUUM INTO ?", destination)
	return err
}
