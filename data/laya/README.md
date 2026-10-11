# Dữ liệu phân loại bài DK-Tech

Nguồn là file dashboard do người dùng gửi ngày 11/10/2026. Chỉ lấy nội dung 175 bài viết: không dùng status Laya cũ, điểm rule, tên group hay lịch sử comment làm đáp án hoặc đặc trưng học.

Nhãn do trợ lý đọc nội dung gán, chưa được người dùng xác nhận độc lập:

| Nhãn | Số bài nguồn | Ý nghĩa |
|---|---:|---|
| self_promotion | 135 | Tác giả tự chào bán dịch vụ hoặc sản phẩm |
| service_request | 27 | Khách cần mua/thuê người thực hiện công việc hoặc dự án |
| other | 12 | Chia sẻ, khảo sát, chào nhóm, hỏi thông tin, mời dùng thử |
| recruitment | 1 | Tuyển nhân viên vào đội ngũ |

Thuê freelancer theo sản phẩm vẫn là `service_request`; tuyển nhân sự có vị trí, lương và CV là `recruitment`. Bài "Cần API giải captcha" trong nguồn là quảng cáo vì phần còn lại chào bán API và link đăng ký. Bài middleware KiotViet là nhu cầu thuê dự án dù có hashtag tuyển dụng.

`posts_labeled.jsonl` giữ đủ 175 bài gốc, ID, nhãn, lý do và checksum nguồn. `LABELS.md` là bản đọc nhanh. `post_type_dataset.jsonl` gộp các nội dung lặp thành 102 mẫu, ghép mẫu gần giống trước khi chia tập; 3 mẫu chưa rõ giữ `review_only` và không học. Có 82 mẫu bổ sung tự soạn, được ghi rõ `origin=synthetic_assistant`; không phải bài Facebook thực tế.

Tập học có 126 mẫu, validation có 30 mẫu; tập so sánh có 19 bài thật và 6 mẫu tuyển dụng tự soạn. Bài tuyển dụng thật duy nhất được đưa vào tập học, nên khả năng phân biệt tuyển dụng ngoài thực tế chưa có phép đo độc lập. Tập so sánh giữ riêng khỏi các cập nhật trọng số và calibration, nhưng đã được xem kết quả qua các lần thử kiến trúc; vì vậy kết quả là đánh giá thăm dò trên mẫu nhỏ.

Máy dùng CPU. Đầu phân loại bốn nhãn được huấn luyện trên biểu diễn CLS và trung bình token của encoder Laya đã đóng băng, kết hợp đặc trưng từ/cặp từ TF-IDF chỉ xây từ tập học. Trọng số đầu phân loại và bộ chuẩn hóa được lưu trong `.local/laya-training/encoder-head-v1/scorer.safetensors`; giữ model gốc để xét nhóm dịch vụ và an toàn. Bản thử fine-tune native scorer trước đó được lưu riêng và không được kích hoạt vì không cải thiện đủ.

Chạy lại trong thư mục dự án:

```powershell
.\.venv\Scripts\python.exe scripts\label-laya-data.py
.\.venv\Scripts\python.exe scripts\train-laya-encoder-head.py
.\.venv\Scripts\python.exe scripts\activate-laya-model.py .local\laya-training\encoder-head-v1
```

Đọc `report.json` và `predictions.jsonl` của lượt train trước khi đổi `active.json`. Kích hoạt chỉ dùng manifest đạt phép kiểm tra cục bộ; app kiểm tra checksum trọng số và config model gốc khi nạp. Model mới không tự thay thế kết quả đang lưu cho tới khi backend khởi động lại với phiên bản bộ phân loại mới.

Nguồn kỹ thuật: [Laya fine-tuning](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md), mã `DecisionModel` và encoder trong thư viện `laya==0.3.20` cài tại dự án.
