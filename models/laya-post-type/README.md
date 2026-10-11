# Đầu phân loại Laya đã train

Thư mục này chứa trọng số đã train ngày 11/10/2026, dùng cho bốn loại bài:
tìm nhà cung cấp, tuyển dụng, tự quảng cáo và bài khác.

- `active.json` chọn release theo checksum.
- `releases/<checksum>/manifest.json` chứa cấu hình, vocabulary và checksum.
- `releases/<checksum>/scorer.safetensors` là trọng số thực, khoảng 1,6 MB.

Clone/pull repo là có sẵn bản đã train. `setup-tool.cmd` chuẩn bị model nền
Laya/Qwen và thư viện; không huấn luyện lại. Model đã kích hoạt riêng trong
`.local/laya-training/active.json` được ưu tiên nếu tồn tại.

Phương pháp, kết quả và giới hạn: `data/laya/TRAINING_REPORT.md`.
