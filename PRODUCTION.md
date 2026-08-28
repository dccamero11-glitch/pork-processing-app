# Production readiness

ระบบยังรันในเครื่องด้วย SQLite (`processing.db`) เพื่อรักษาข้อมูลเดิม แต่พร้อมสลับเป็น PostgreSQL ผ่าน `DATABASE_URL`

## บัญชีผู้ใช้

- `admin` — ดูและบันทึกได้ทุกสาขา
- `manager_bangbuathong` — บางบัวทอง
- `manager_trang` — ตรัง
- `manager_langsuan` — หลังสวน

Local development defaults ใช้เพื่อทดสอบเท่านั้น: admin ใช้ `admin123` และ manager ใช้ `manager123` ต้องตั้งรหัสใหม่ผ่าน environment variables ก่อน Production

## เตรียม PostgreSQL

1. สร้าง PostgreSQL database
2. ติดตั้ง `pip install -r requirements-production.txt`
3. ตั้ง `DATABASE_URL`
4. รัน `python migrate_sqlite_to_postgres.py` เพียงครั้งเดียว
5. เก็บไฟล์ `processing.db` เดิมไว้เป็น backup

## Production / Deploy

สร้างค่าตาม `.env.example` ใน Secret Manager ของผู้ให้บริการ ห้าม commit ค่า secret จริง ระบบจะไม่เริ่มใน Production หากขาด Database, Login passwords, `AUTH_SECRET` หรือ OpenAI key

Docker image พร้อม build จาก `Dockerfile` แต่ยังไม่มีการ Deploy ตามคำสั่งผู้ใช้ ขั้นออนไลน์ที่เหลือคือสร้าง PostgreSQL, ตั้ง domain/HTTPS, secrets, automated backups และ monitoring
