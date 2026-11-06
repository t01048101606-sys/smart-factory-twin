-- 설비 이벤트 테이블: 트윈이 내보내는 공통 이벤트(docs/event_schema.json)를 그대로 보관한다.
-- Auto Parts MES의 기존 테이블은 건드리지 않고, 이 테이블 하나만 추가한다.
-- event_id가 기본키라서 같은 이벤트를 두 번 넣어도 중복되지 않는다.
CREATE TABLE IF NOT EXISTS machine_event (
    event_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    line_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    piece_id TEXT,
    work_order_id INTEGER,
    payload TEXT NOT NULL,
    sim_t REAL,
    FOREIGN KEY (work_order_id) REFERENCES work_order (work_order_id)
);
CREATE INDEX IF NOT EXISTS idx_machine_event_type_ts ON machine_event (event_type, ts);
CREATE INDEX IF NOT EXISTS idx_machine_event_piece ON machine_event (piece_id);
CREATE INDEX IF NOT EXISTS idx_machine_event_wo ON machine_event (work_order_id);
