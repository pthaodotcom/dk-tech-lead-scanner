# Kiểm tra request Facebook của DK-Tech

Đây là tiện ích quét thử nghiệm v0.2.0. Phần đọc group/bài chỉ đọc; phần comment chỉ gửi sau hai bước kiểm tra và xác nhận trên đúng bài đã chỉ định. Tự viết cho bài test; không cài hoặc thực thi extension bên thứ ba.

Page đối chiếu: https://www.facebook.com/dktechsupport/ — ID `61593769810301`, lấy từ metadata công khai của chính URL này.

## Nạp vào Chrome

1. Mở `chrome://extensions`, bật **Chế độ dành cho nhà phát triển**.
2. Chọn **Tải tiện ích đã giải nén**, trỏ đến thư mục `diagnostics/facebook-request-probe` cạnh file này.
3. Đăng nhập Facebook trong Chrome và chuyển sang Page DK-Tech. Reload tab sau khi cài extension.
4. Mở **Nhóm của bạn / nhóm đã tham gia**, đổi mục **Sắp xếp** để Facebook phát sinh query danh sách. Mở tiện ích **DK-Tech — kiểm tra request Facebook**. Tiện ích phải hiện `v0.2.0`; nếu còn bản cũ, bấm biểu tượng tải lại ở `chrome://extensions` rồi mở lại tab Facebook.
5. Bấm **Xem request đã ghi nhận**, sau đó **Thử đọc lại bằng request**. ID Page đã điền sẵn.
6. Giữ tab danh sách nhóm mở. Mở thêm một tab group mà Page đang tham gia và tải thêm bài để bắt query feed.
7. Bấm **Quét group và bài, chống trùng**. Tiện ích lấy hết cursor danh sách group, sau đó dùng query feed đã bắt để đọc từng group theo giới hạn số trang đã chọn.

Tiện ích quan sát query đọc danh sách nhóm và feed, tự nhận diện tên query hiện tại hoặc cấu trúc response tương đương. Không điền mật khẩu, cookie hay token vào tiện ích. Nếu Facebook không phát sinh query được nhận diện, kết quả là UNAVAILABLE; không suy diễn thành công.

Lịch sử chống trùng chỉ lưu `groupId`, `postId`, thời gian thấy lần đầu/lần cuối và hash nội dung trong `localStorage` của Facebook, tối đa 20.000 bài. Nội dung bài chỉ nằm trong kết quả quét của tab để chuyển sang bước lọc/LLM; receiver chẩn đoán không lưu nội dung này.

## Thử một comment đã được người dùng chỉ định

Bài test cố định: `https://www.facebook.com/groups/1163787441488087/posts/1802484360951722/`; nội dung chính xác: `ib hoặc liên hệ 0342391808 ạ`. Bản này chỉ nhận Page `61593769810301`.

1. Sau khi nạp lại tiện ích ở `chrome://extensions`, mở đúng link bài bằng Page DK-Tech rồi reload trang và đợi bài tải.
2. Nhập một nội dung mới, không trùng comment đang có. Bấm **Kiểm tra bài, Page và mutation**.
3. Chỉ khi trạng thái `READY`, `feedbackReady: true`, `mutationReady: true` và nội dung chưa xuất hiện thì tick xác nhận. Token xác nhận hết hạn sau 2 phút.
4. Bấm **Gửi đúng một comment thử**. `PASS` chỉ được trả khi response có comment ID và không có lỗi GraphQL; `PASS_WITH_WARNINGS` dùng khi có comment ID nhưng response còn chứa lỗi GraphQL. `FAIL`/`INCONCLUSIVE` vẫn khóa lần thử lại cùng nội dung để tránh đăng trùng.

Nếu nút 3 trả `INCONCLUSIVE`, popup chưa bắt được mã phản hồi của bài. Gửi báo cáo để kiểm tra tiếp. Nút gửi không làm việc trên bài khác, danh tính khác hoặc khi chưa đối chiếu được bài đích. Comment là hành động công khai trên Facebook.

## Báo cáo

Codex có thể chạy `python diagnostics/receive-report.py`. Dịch vụ chỉ nghe `127.0.0.1:9340`, nhận báo cáo từ extension, không gọi Facebook. Báo cáo nằm ở `.local/facebook-test-results` (được gitignore). Tiện ích không xuất cookie, token, request body hoặc nội dung bài; chỉ gửi loại query, ID danh tính, HTTP status, số kết quả và tối đa 5 ID mẫu (tên group nếu có). Báo cáo comment có nội dung comment cố định người dùng đã cung cấp và ID comment nếu thành công.

Nếu receiver chưa chạy, kết quả vẫn hiện trong popup. Giữ popup mở trong khi test; đóng popup có thể làm mất báo cáo.

## Cách đọc kết quả

- PASS: query đọc đúng loại, đúng ID Page được chỉ định, HTTP thành công, không có lỗi GraphQL và đọc được ít nhất một phần tử đúng cấu trúc.
- FAIL: HTTP/GraphQL lỗi hoặc lỗi mạng.
- INCONCLUSIVE: trả lời thành công nhưng chưa nhận diện được phần tử; không đồng nghĩa dữ liệu trống thật.
- UNAVAILABLE: chưa bắt được query trong tab này.
- BLOCKED: chưa xác nhận được danh tính Page hoặc điều kiện chỉ đọc.

PASS cho đọc bài không chứng minh lấy đủ danh sách hay phân trang hoạt động. PASS cho gửi comment cần server trả ID comment; nếu là `PASS_WITH_WARNINGS` phải đối chiếu comment trên DOM sau khi tải lại. Ngắt extension khi xong; reload Facebook để gỡ các hook quan sát khỏi tab.

Kết quả `group_posts` chỉ đếm node `Story` trong feed. `hasText` và `textLength` là kiểm tra khả năng lấy nội dung văn bản; `false` chưa chứng minh bài không có chữ vì Facebook có nhiều cấu trúc nội dung khác nhau.

## Phát hiện Facebook thay đổi

`inspect().compatibility` trả cảnh báo:

- `QUERY_NAME_CHANGED`: tên query không còn nằm trong danh sách biết trước nhưng response vẫn nhận diện được theo node `Group`/`Story` và đường dẫn feed.
- `RESPONSE_SHAPE_UNRECOGNIZED`: query trả HTTP thành công nhưng parser không còn nhận diện được dữ liệu.
- `QUERY_SHAPE_CHANGED`: loại dữ liệu thực tế khác loại dự kiến.

Khi có cảnh báo, tool dừng kết luận PASS cho phần bị ảnh hưởng và lưu tên query, không lưu token hoặc body.

## Phạm vi kỹ thuật

Không dùng DOM làm nguồn thu thập bài. Content script trong MAIN world quan sát `fetch` và `XMLHttpRequest`; chỉ giữ request cần thiết trong bộ nhớ tab. Query đọc được phát lại sau khi đối chiếu `av` và danh tính hiện tại. Mutation lấy `doc_id` từ Relay artifact hiện tại, không dùng ID dự phòng cũ, và chỉ gửi tối đa một lần cho mỗi nội dung đã xác nhận trên bài cố định.

Gói bên thứ ba đã đọc trước đó chỉ là tham khảo bằng chứng về cơ chế. Bài test có một doc_id dự phòng có thể lỗi thời; không gọi máy chủ cấu hình hoặc máy chủ tác giả.
