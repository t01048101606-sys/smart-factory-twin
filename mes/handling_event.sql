-- 현장 모니터링(충격, 초음파, 온습도 센서) 이력 테이블.
-- MES 원본 저장소의 sql/schema.sql 에는 없는데 src/queries.py 는 이 테이블을 읽는다 (출하 관리 페이지의 충격 이력 배지 등).
-- 그래서 원본 그대로는 출하 관리 페이지가 "no such table: handling_event" 오류로 열리지 않는다.
-- 열은 src/queries.py 가 읽는 이름 그대로이고, 센서 이력이 없으면 비어 있다 (충격 배지가 표시되지 않을 뿐 정상).
CREATE TABLE IF NOT EXISTS handling_event (
    handling_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id            INTEGER REFERENCES lot(lot_id),
    event_date        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    distance_cm       REAL,
    shock_detected    TEXT NOT NULL DEFAULT 'N' CHECK (shock_detected IN ('Y', 'N')),
    temperature       REAL,
    humidity          REAL,
    alert_triggered   TEXT NOT NULL DEFAULT 'N' CHECK (alert_triggered IN ('Y', 'N'))
);
CREATE INDEX IF NOT EXISTS idx_handling_event_lot ON handling_event(lot_id);
