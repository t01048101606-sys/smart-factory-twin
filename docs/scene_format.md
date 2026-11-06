# 3D 장면 정의 (JSON)

`src/scenes/*.json` 은 3D 공정 화면의 **무엇을 어디에 그리고, 어떤 상태 값에 따라 어떻게 움직이는지**를 적은 파일입니다.
범용 뷰어(`src/static/linescene.js`)가 이 파일과 상태(`/api/line/state`)만으로 화면을 그리므로, 새 공정은 JSON을 새로 만들고
같은 모양의 상태를 내보내면 됩니다. 단위는 1 = 약 10 cm, 좌표는 x(가로), y(높이), z(앞뒤)입니다.

## 최상위

| 키 | 내용 |
|---|---|
| `title` | 화면 제목 |
| `background` | 배경색 (`#rrggbb`) |
| `camera` | `{position:[x,y,z], target:[x,y,z]}` 처음 시점 |
| `fit` | `{width, height}` 장면의 가로, 세로 크기. 있으면 창 크기에 맞춰 대각선 시점의 거리를 자동으로 정함 (사용자가 직접 돌리거나 다른 시점을 고르면 그대로 둠) |
| `views` | 시점 버튼 `{이름: {position, target}}` (이름: diag, front, top, side) |
| `objects` | 그릴 오브젝트 목록 |
| `parts` | 움직이는 부품 설정 |

## 오브젝트 (`objects`)

공통: `id`, `pos:[x,y,z]`, `color`(`#rrggbb`), `opacity`(0~1, 있으면 반투명)

| `shape` | 추가 키 |
|---|---|
| `box` | `size:[가로,높이,깊이]` |
| `cylinder` | `r`(반지름), `h`(높이), 선택: `rt`/`rb`(윗면/아랫면 반지름, 원뿔 모양) |
| `sphere` | `r` |
| `belt` | `size:[길이,폭]`, `path`(움직임 여부 상태 값). 줄무늬가 움직이는 컨베이어 윗면 |
| `label` | `text`, `w`(너비). 이름표 |

### 움직임 연결 (`anim`)

상태 값(`path`, 예: `"stations.press.ram"`)에 따라 오브젝트를 바꿉니다.

| `prop` | 동작 |
|---|---|
| `x` / `y` / `z` | 값(0~1)에 따라 `from` ~ `to` 사이로 이동 (부드럽게 따라감) |
| `visible` | 값이 참일 때만 보임 |
| `emissive` | 값이 참이면 `on` 색, 아니면 `off` 색으로 빛남 |
| `lamp` | 값(문자열)을 `map`의 색으로 바꾸고 빛냄 (공정 상태 램프) |
| `color` | 값(문자열)을 `map`의 색으로 바꿈 (없으면 `default`) |

## 부품 (`parts`)

| 키 | 내용 |
|---|---|
| `size` | 부품 상자 크기 |
| `colors` | 진행 상태별 색: `normal`, `pressed`, `welded`, `painted`, `defect` |
| `segments` | 칸 이름 -> `[시작점, 끝점]`. 부품은 `state.parts[i].stage` 칸에서 `t`(0~1)에 따라 두 점 사이를 이동 |

## 상태가 지켜야 할 모양 (`/api/line/state`)

```
{ "stations": {"press": {"state": "working|blocked|starved|down", "ram": 0~1, ...}, ...},
  "conveyors": {"c1": {"moving": true}, ...},
  "parts": [{"id": 1, "stage": "press", "t": 0.4, "pressed": true, "welded": false, "painted": false, "defect": false}],
  "counts": {"in": 0, "good": 0, "scrap": 0}, "util": {...}, "kpi": {...}, "fault": "none", "speed": 1 }
```

`tests/test_linescene.py` 가 장면 JSON의 모든 `path`가 시뮬레이터 상태에 있는지, 부품 칸 이름이 시뮬레이터와 같은지 확인합니다.

## 새 공정을 추가하려면

1. 공정 시뮬레이터가 위와 같은 모양의 상태를 돌려주게 만든다 (`src/line_sim.py` 참고).
2. `src/scenes/` 에 장면 JSON을 만든다 (오브젝트와 `anim`, `parts.segments`).
3. 서버(`server.py`)에서 그 시뮬레이터와 장면 파일을 연결한다.
