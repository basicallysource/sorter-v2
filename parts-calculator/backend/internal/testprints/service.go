package testprints

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"unicode/utf8"

	"connectrpc.com/connect"
	pb "github.com/basicallysource/sorter-v2/parts-calculator/backend/gen/testprints/v1"
	"github.com/google/uuid"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func (s *Server) GetSession(ctx context.Context, _ *connect.Request[pb.GetSessionRequest]) (*connect.Response[pb.GetSessionResponse], error) {
	who := actor(ctx).who
	return connect.NewResponse(&pb.GetSessionResponse{SignedIn: who.Account != "", Admin: who.In(ADMIN_GROUP), Handle: who.Handle, SigninUrl: s.auth.SignInURL("/admin")}), nil
}

func (s *Server) ListBoards(ctx context.Context, _ *connect.Request[pb.ListBoardsRequest]) (*connect.Response[pb.ListBoardsResponse], error) {
	result := &pb.ListBoardsResponse{}
	for _, board := range s.cfg.Boards {
		result.Boards = append(result.Boards, &pb.Board{Id: board.ID, Audience: board.Audience})
	}
	return connect.NewResponse(result), nil
}

func (s *Server) ListTests(ctx context.Context, req *connect.Request[pb.ListTestsRequest]) (*connect.Response[pb.ListTestsResponse], error) {
	if !cursorID(req.Msg.AfterId) {
		return nil, fail(connect.CodeInvalidArgument, "invalid cursor")
	}
	limit := pageSize(req.Msg.Limit)
	p := actor(ctx)
	boards := []any{req.Msg.AfterId}
	marks := []string{}
	for _, board := range s.cfg.Boards {
		if p.who.In(ADMIN_GROUP) || board.Audience == "community" {
			boards = append(boards, board.ID)
			marks = append(marks, "?")
		}
	}
	result := &pb.ListTestsResponse{}
	if len(marks) == 0 {
		return connect.NewResponse(result), nil
	}
	query := "SELECT body FROM tests WHERE id > ? AND board_id IN (" + strings.Join(marks, ",") + ")"
	if !p.who.In(ADMIN_GROUP) || !req.Msg.IncludeDrafts {
		query += " AND state != 'draft'"
	}
	query += " ORDER BY id LIMIT ?"
	boards = append(boards, limit+1)
	rows, err := s.db.QueryContext(ctx, query, boards...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var body []byte
		if err = rows.Scan(&body); err != nil {
			return nil, err
		}
		test := &pb.TestCase{}
		if err = protojson.Unmarshal(body, test); err != nil {
			return nil, err
		}
		if len(result.Tests) == limit {
			result.NextAfterId = result.Tests[limit-1].Id
			break
		}
		result.Tests = append(result.Tests, test)
	}
	return connect.NewResponse(result), rows.Err()
}

func (s *Server) GetTest(ctx context.Context, req *connect.Request[pb.GetTestRequest]) (*connect.Response[pb.GetTestResponse], error) {
	if !validID(req.Msg.Id) || !cursorID(req.Msg.FeedbackAfterId) {
		return nil, fail(connect.CodeInvalidArgument, "invalid id")
	}
	test, err := readTest(ctx, s.db, req.Msg.Id)
	if err != nil {
		return nil, err
	}
	if !s.canRead(actor(ctx), test) {
		return nil, fail(connect.CodeNotFound, "test not found")
	}
	result := &pb.GetTestResponse{Test: test}
	rows, err := s.db.QueryContext(ctx, "SELECT actor_id,display_name,created_at FROM claims WHERE test_id=? AND active=1 ORDER BY actor_id LIMIT 100", test.Id)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		claim := &pb.Claim{}
		if err = rows.Scan(&claim.ActorId, &claim.DisplayName, &claim.CreatedAt); err != nil {
			rows.Close()
			return nil, err
		}
		result.Claims = append(result.Claims, claim)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	rows, err = s.db.QueryContext(ctx, "SELECT body FROM feedback WHERE test_id=? AND deleted=0 AND id>? ORDER BY id LIMIT 51", test.Id, req.Msg.FeedbackAfterId)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var body []byte
		if err = rows.Scan(&body); err != nil {
			return nil, err
		}
		feedback := &pb.Feedback{}
		if err = protojson.Unmarshal(body, feedback); err != nil {
			return nil, err
		}
		if len(result.Feedback) == 50 {
			result.NextFeedbackAfterId = result.Feedback[49].Id
			break
		}
		result.Feedback = append(result.Feedback, feedback)
	}
	return connect.NewResponse(result), rows.Err()
}

func (s *Server) SaveTest(ctx context.Context, req *connect.Request[pb.SaveTestRequest]) (*connect.Response[pb.SaveTestResponse], error) {
	input := req.Msg
	if !validID(input.RequestId) || input.Test == nil {
		return nil, fail(connect.CodeInvalidArgument, "request id and test required")
	}
	if err := s.validateTest(input.Test); err != nil {
		return nil, err
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(input)
	if err != nil {
		return nil, err
	}
	digest := hashBytes(encoded)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	result := &pb.SaveTestResponse{}
	scope := "admin:" + actor(ctx).who.Account
	if found, err := receipt(ctx, tx, scope, input.RequestId, digest, result); err != nil || found {
		return connect.NewResponse(result), err
	}
	test := proto.Clone(input.Test).(*pb.TestCase)
	test.UpdatedAt = now()
	if test.Id == "" {
		if input.ExpectedRevision != 0 || test.State != "draft" || len(test.Assets) > 0 {
			return nil, fail(connect.CodeInvalidArgument, "new tests must be empty drafts at revision zero")
		}
		test.Id = newID()
		test.CreatedAt = test.UpdatedAt
		test.Revision = 1
		test.ClaimCount = 0
		test.FeedbackCount = 0
	} else {
		previous, err := readTest(ctx, tx, test.Id)
		if err != nil {
			return nil, err
		}
		if previous.Revision != input.ExpectedRevision {
			return nil, fail(connect.CodeAborted, "test changed; reload before saving")
		}
		if !transition(previous.State, test.State) {
			return nil, fail(connect.CodeFailedPrecondition, "invalid state transition")
		}
		if previous.State != "draft" {
			a := proto.Clone(previous).(*pb.TestCase)
			b := proto.Clone(test).(*pb.TestCase)
			if a.BoardId != b.BoardId || a.Kind != b.Kind || !sameReferences(a.References, b.References) || !sameAssets(a.Assets, b.Assets) {
				return nil, fail(connect.CodeFailedPrecondition, "published targets are immutable; create a new test for a new version")
			}
		}
		test.CreatedAt = previous.CreatedAt
		test.Revision = previous.Revision + 1
		test.ClaimCount = previous.ClaimCount
		test.FeedbackCount = previous.FeedbackCount
	}
	if test.State != "draft" && len(test.References) == 0 {
		return nil, fail(connect.CodeInvalidArgument, "a pinned version reference is required to publish")
	}
	assets := []*pb.Asset{}
	for _, asset := range test.Assets {
		canonical, err := readAsset(ctx, tx, test.Id, asset.Id, "model")
		if err != nil {
			return nil, err
		}
		assets = append(assets, canonical)
	}
	test.Assets = assets
	if err = writeTest(ctx, tx, test, test.State != "draft"); err != nil {
		return nil, err
	}
	if err = audit(ctx, tx, actor(ctx).who.Account, "save", test.Id); err != nil {
		return nil, err
	}
	result.Test = test
	if err = saveReceipt(ctx, tx, scope, input.RequestId, digest, result); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return connect.NewResponse(result), nil
}

func (s *Server) validateTest(test *pb.TestCase) error {
	if !cursorID(test.Id) || !validText(test.Title, 1, 160) || !validText(test.Instructions, 0, 12000) || !slices.Contains([]string{"part", "assembly", "document"}, test.Kind) || !slices.Contains([]string{"draft", "open", "closed", "archived"}, test.State) {
		return fail(connect.CodeInvalidArgument, "invalid test fields")
	}
	if _, ok := s.boards[test.BoardId]; !ok {
		return fail(connect.CodeInvalidArgument, "unknown board")
	}
	if len(test.References) > 32 || len(test.Assets) > 32 {
		return fail(connect.CodeInvalidArgument, "too many references or assets")
	}
	for _, ref := range test.References {
		if ref == nil || !ONSHAPE_ID.MatchString(ref.DocumentId) || !ONSHAPE_ID.MatchString(ref.VersionId) || !ONSHAPE_ID.MatchString(ref.ElementId) || !validText(ref.PartId, 0, 128) || !validText(ref.Label, 0, 160) {
			return fail(connect.CodeInvalidArgument, "references require document, version and element ids")
		}
	}
	seen := map[string]bool{}
	for _, asset := range test.Assets {
		if asset == nil || !validID(asset.Id) || seen[asset.Id] {
			return fail(connect.CodeInvalidArgument, "invalid asset ids")
		}
		seen[asset.Id] = true
	}
	return nil
}

func transition(from, to string) bool {
	return from == to || from == "draft" && to == "open" || from == "open" && (to == "closed" || to == "archived") || from == "closed" && (to == "open" || to == "archived")
}
func validID(value string) bool {
	id, err := uuid.Parse(value)
	return err == nil && id.Version() == 7 && id.String() == value
}
func cursorID(value string) bool { return value == "" || validID(value) }
func validText(value string, min, max int) bool {
	return utf8.ValidString(value) && len(strings.TrimSpace(value)) >= min && len(value) <= max && !strings.ContainsRune(value, 0)
}
func pageSize(limit int32) int {
	if limit <= 0 {
		return 50
	}
	if limit > MAX_PAGE {
		return MAX_PAGE
	}
	return int(limit)
}
func sameReferences(a, b []*pb.OnshapeReference) bool {
	return proto.Equal(&pb.TestCase{References: a}, &pb.TestCase{References: b})
}
func sameAssets(a, b []*pb.Asset) bool {
	aa, bb := []string{}, []string{}
	for _, v := range a {
		aa = append(aa, v.Id)
	}
	for _, v := range b {
		bb = append(bb, v.Id)
	}
	return slices.Equal(aa, bb)
}
func readAsset(ctx context.Context, db queryer, test_id, asset_id, purpose string) (*pb.Asset, error) {
	var body []byte
	if err := db.QueryRowContext(ctx, "SELECT body FROM assets WHERE id=? AND test_id=? AND purpose=?", asset_id, test_id, purpose).Scan(&body); err != nil {
		return nil, fail(connect.CodeInvalidArgument, fmt.Sprintf("asset unavailable for this %s", purpose))
	}
	asset := &pb.Asset{}
	return asset, protojson.Unmarshal(body, asset)
}
