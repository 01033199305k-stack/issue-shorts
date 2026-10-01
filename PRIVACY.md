# issue-shorts 개인정보처리방침 · Privacy Policy

최종 수정: 2026-10-01

## 한국어

issue-shorts 는 채널 운영자가 자기 유튜브 채널에 직접 만든 이슈 쇼츠 영상을 올리기 위해 쓰는 내부 자동화 도구입니다.
다른 사용자에게 제공하는 서비스가 아닙니다.

**수집하는 정보**
- 이용자 개인정보를 수집하지 않습니다.
- YouTube API 서비스는 운영자 본인의 YouTube 채널에 운영자가 만든 동영상을 업로드(예약 공개 포함)하는 데에만 씁니다
  (범위: 동영상 업로드 `youtube.upload`, 연결된 채널 확인용 `youtube.readonly`).

**보관**
- OAuth 클라이언트 정보와 리프레시 토큰은 GitHub Actions 의 암호화된 시크릿에만 보관합니다.
- YouTube 에서 받는 데이터는 업로드한 동영상의 ID·주소·공개 예정 시각뿐이며, 이 저장소의 기록(`state/history.json`)에만 남깁니다.
- YouTube 의 조회수·댓글·구독자 등 다른 API 데이터는 가져오거나 저장하지 않습니다.
- 어떤 데이터도 제3자에게 판매하거나 공유하지 않습니다.

**보관 기간과 삭제**
- 기록의 동영상 ID·주소는 게시 이력으로 보관하며, 삭제를 요청하면 7일 안에 지웁니다.
- 접근 권한을 철회하면 리프레시 토큰은 즉시 무효가 되며, 저장된 토큰은 7일 안에 GitHub 시크릿에서 삭제합니다.
- 삭제 요청: alsgur3319@naver.com

**권한 철회**
- https://myaccount.google.com/permissions 에서 언제든 issue-shorts 의 접근 권한을 철회할 수 있습니다.
- 이 도구는 YouTube API 서비스를 사용합니다. [YouTube 서비스 약관](https://www.youtube.com/t/terms)과
  [Google 개인정보처리방침](https://policies.google.com/privacy)이 함께 적용됩니다.

**문의**: alsgur3319@naver.com

## English

issue-shorts is an internal automation tool used only by the channel operator to publish short videos the operator
created to the operator's own YouTube channel. It is not offered to any other users.

**Information we collect**
- We do not collect personal information from anyone.
- YouTube API Services are used only to upload (and schedule) videos created by the operator to the operator's own
  YouTube channel (scopes: `youtube.upload` for the upload and `youtube.readonly` to confirm the connected channel).

**Storage**
- The OAuth client credentials and refresh token are stored only as encrypted GitHub Actions secrets.
- The only data received from YouTube is the ID/URL/scheduled time of each uploaded video, kept in this repository's log (`state/history.json`).
- No other YouTube API data (views, comments, subscribers, etc.) is retrieved or stored.
- No data is sold or shared with third parties.

**Retention and deletion**
- Video IDs/URLs in the log are kept as publishing history and are deleted within 7 days of a deletion request.
- If access is revoked, the refresh token stops working immediately, and the stored token is deleted from GitHub secrets within 7 days.
- Deletion requests: alsgur3319@naver.com

**Revoking access**
- Access can be revoked at any time at https://myaccount.google.com/permissions.
- This tool uses YouTube API Services. By using it you are also subject to the
  [YouTube Terms of Service](https://www.youtube.com/t/terms) and the [Google Privacy Policy](https://policies.google.com/privacy).

**Contact**: alsgur3319@naver.com
