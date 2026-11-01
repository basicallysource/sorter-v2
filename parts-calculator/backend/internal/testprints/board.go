package testprints

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"slices"
	"time"

	"connectrpc.com/connect"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const EVENT_TIME = "2006-01-02T15:04:05.000000000Z"

func (s *Server) SyncChanges(ctx context.Context, req *connect.Request[pb.SyncChangesRequest]) (*connect.Response[pb.SyncChangesResponse], error) {
	if req.Msg.AfterSequence < 0 {
		return nil, fail(connect.CodeInvalidArgument, "negative cursor")
	}
	board := actor(ctx).board
	result := &pb.SyncChangesResponse{BoardId: board.ID, GuildId: board.GuildID, ForumId: board.ForumID, Audience: board.Audience, NextSequence: req.Msg.AfterSequence}
	limit := pageSize(req.Msg.Limit)
	rows, err := s.db.QueryContext(ctx, "SELECT sequence,body FROM changes WHERE board_id=? AND sequence>? ORDER BY sequence LIMIT ?", board.ID, req.Msg.AfterSequence, limit+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		change := &pb.Change{Test: &pb.TestCase{}}
		var body []byte
		if err = rows.Scan(&change.Sequence, &body); err != nil {
			return nil, err
		}
		if err = protojson.Unmarshal(body, change.Test); err != nil {
			return nil, err
		}
		if len(result.Changes) == limit {
			result.HasMore = true
			break
		}
		result.Changes = append(result.Changes, change)
		result.NextSequence = change.Sequence
	}
	return connect.NewResponse(result), rows.Err()
}

func (s *Server) BindThread(ctx context.Context, req *connect.Request[pb.BindThreadRequest]) (*connect.Response[pb.BindThreadResponse], error) {
	input := req.Msg
	board := actor(ctx).board
	if input.GuildId != board.GuildID || input.ForumId != board.ForumID || !SNOWFLAKE.MatchString(input.ThreadId) || !validID(input.TestId) {
		return nil, fail(connect.CodePermissionDenied, "board binding refused")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	test, err := readTest(ctx, tx, input.TestId)
	if err != nil {
		return nil, err
	}
	if test.BoardId != board.ID || test.State == "draft" {
		return nil, fail(connect.CodeNotFound, "test not found")
	}
	var bound string
	err = tx.QueryRowContext(ctx, "SELECT thread_id FROM bindings WHERE test_id=?", test.Id).Scan(&bound)
	if err == nil && bound != input.ThreadId {
		return nil, fail(connect.CodeAlreadyExists, "test already bound")
	}
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	if bound == "" {
		if _, err = tx.ExecContext(ctx, "INSERT INTO bindings(test_id,board_id,thread_id) VALUES(?,?,?)", test.Id, board.ID, input.ThreadId); err != nil {
			return nil, fail(connect.CodeAlreadyExists, "thread already bound")
		}
		if err = audit(ctx, tx, "board:"+board.ID, "bind", test.Id); err != nil {
			return nil, err
		}
	}
	return connect.NewResponse(&pb.BindThreadResponse{}), tx.Commit()
}

func (s *Server) ApplyEvent(ctx context.Context, req *connect.Request[pb.ApplyEventRequest]) (*connect.Response[pb.ApplyEventResponse], error) {
	input := req.Msg
	board := actor(ctx).board
	if !DIGEST.MatchString(input.EventId) || !validID(input.TestId) || !SNOWFLAKE.MatchString(input.MessageId) || !SNOWFLAKE.MatchString(input.ActorId) || !validText(input.DisplayName, 1, 128) || !validText(input.Body, 0, 8000) || len(input.AssetIds) > 10 || !slices.Contains([]string{"claim", "release", "feedback", "delete_feedback"}, input.Kind) {
		return nil, fail(connect.CodeInvalidArgument, "invalid event")
	}
	stamp, err := time.Parse(time.RFC3339Nano, input.OccurredAt)
	if err != nil || stamp.Before(time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)) || stamp.After(time.Now().Add(5*time.Minute)) {
		return nil, fail(connect.CodeInvalidArgument, "invalid event timestamp")
	}
	changed_at := stamp.UTC().Format(EVENT_TIME)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(input)
	if err != nil {
		return nil, err
	}
	digest := hashBytes(encoded)
	scope := "board:" + board.ID
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	result := &pb.ApplyEventResponse{}
	if found, err := receipt(ctx, tx, scope, input.EventId, digest, result); err != nil || found {
		if found {
			result.Duplicate = true
		}
		return connect.NewResponse(result), err
	}
	test, err := readTest(ctx, tx, input.TestId)
	if err != nil {
		return nil, err
	}
	if err = boundTest(ctx, tx, board, test, input.GuildId, input.ForumId, input.ThreadId); err != nil {
		return nil, err
	}
	if input.Kind == "claim" || input.Kind == "release" {
		if input.Body != "" || len(input.AssetIds) > 0 {
			return nil, fail(connect.CodeInvalidArgument, "claim events cannot include feedback")
		}
		var previous string
		err = tx.QueryRowContext(ctx, "SELECT changed_at FROM claims WHERE test_id=? AND actor_id=?", test.Id, input.ActorId).Scan(&previous)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return nil, err
		}
		result.Ignored = changed_at <= previous || input.Kind == "claim" && test.State != "open"
		if !result.Ignored {
			active := 0
			if input.Kind == "claim" {
				active = 1
			}
			_, err = tx.ExecContext(ctx, `INSERT INTO claims(test_id,actor_id,display_name,created_at,changed_at,active) VALUES(?,?,?,?,?,?)
 ON CONFLICT(test_id,actor_id) DO UPDATE SET display_name=excluded.display_name,changed_at=excluded.changed_at,active=excluded.active`, test.Id, input.ActorId, input.DisplayName, changed_at, changed_at, active)
			if err != nil {
				return nil, err
			}
		}
	} else {
		result.Ignored, err = applyFeedback(ctx, tx, input, changed_at, board)
		if err != nil {
			return nil, err
		}
	}
	if !result.Ignored {
		if err = tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM claims WHERE test_id=? AND active=1", test.Id).Scan(&test.ClaimCount); err != nil {
			return nil, err
		}
		if err = tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM feedback WHERE test_id=? AND deleted=0", test.Id).Scan(&test.FeedbackCount); err != nil {
			return nil, err
		}
		test.Revision++
		test.UpdatedAt = now()
		if err = writeTest(ctx, tx, test, true); err != nil {
			return nil, err
		}
		if err = audit(ctx, tx, scope+":"+input.ActorId, input.Kind, test.Id); err != nil {
			return nil, err
		}
	}
	if err = saveReceipt(ctx, tx, scope, input.EventId, digest, result); err != nil {
		return nil, err
	}
	return connect.NewResponse(result), tx.Commit()
}

func boundTest(ctx context.Context, db queryer, board *BoardConfig, test *pb.TestCase, guild_id, forum_id, thread_id string) error {
	if test.BoardId != board.ID || test.State == "draft" || guild_id != board.GuildID || forum_id != board.ForumID {
		return fail(connect.CodeNotFound, "test not found")
	}
	var bound string
	if err := db.QueryRowContext(ctx, "SELECT thread_id FROM bindings WHERE test_id=? AND board_id=?", test.Id, board.ID).Scan(&bound); err != nil || bound != thread_id {
		return fail(connect.CodePermissionDenied, "thread binding required")
	}
	return nil
}

func applyFeedback(ctx context.Context, tx *sql.Tx, input *pb.ApplyEventRequest, changed_at string, board *BoardConfig) (bool, error) {
	var body []byte
	var previous, owner string
	var deleted int
	err := tx.QueryRowContext(ctx, "SELECT body,changed_at,actor_id,deleted FROM feedback WHERE test_id=? AND message_id=?", input.TestId, input.MessageId).Scan(&body, &previous, &owner, &deleted)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return false, err
	}
	// A Discord message cannot be undeleted; delayed edits must not resurrect it.
	if deleted != 0 || input.Kind != "delete_feedback" && changed_at <= previous {
		return true, nil
	}
	if owner != "" && owner != input.ActorId {
		return false, fail(connect.CodePermissionDenied, "feedback author mismatch")
	}
	feedback := &pb.Feedback{Id: newID(), CreatedAt: changed_at}
	if len(body) > 0 {
		if err = protojson.Unmarshal(body, feedback); err != nil {
			return false, err
		}
	}
	feedback.ActorId = input.ActorId
	feedback.DisplayName = input.DisplayName
	feedback.UpdatedAt = changed_at
	feedback.Body = input.Body
	feedback.Assets = nil
	feedback.DiscordUrl = fmt.Sprintf("https://discord.com/channels/%s/%s/%s", board.GuildID, input.ThreadId, input.MessageId)
	if input.Kind == "delete_feedback" {
		deleted = 1
		feedback.Body = ""
		feedback.DisplayName = ""
	} else {
		if input.Body == "" && len(input.AssetIds) == 0 {
			return false, fail(connect.CodeInvalidArgument, "feedback is empty")
		}
		seen := map[string]bool{}
		for _, id := range input.AssetIds {
			if !validID(id) || seen[id] {
				return false, fail(connect.CodeInvalidArgument, "invalid evidence id")
			}
			seen[id] = true
			asset, err := readAsset(ctx, tx, input.TestId, id, "evidence")
			if err != nil {
				return false, err
			}
			feedback.Assets = append(feedback.Assets, asset)
		}
	}
	body, err = protojson.Marshal(feedback)
	if err != nil {
		return false, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO feedback(id,test_id,message_id,actor_id,body,changed_at,deleted) VALUES(?,?,?,?,?,?,?)
 ON CONFLICT(test_id,message_id) DO UPDATE SET body=excluded.body,changed_at=excluded.changed_at,deleted=excluded.deleted`, feedback.Id, input.TestId, input.MessageId, input.ActorId, body, changed_at, deleted)
	return false, err
}
