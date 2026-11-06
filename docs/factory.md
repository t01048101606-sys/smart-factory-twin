# 스마트 팩토리 통합 화면

가공 라인(PLC), 프레스 · 용접 · 도장 라인, **물류 · 출하 구역**(`logistics.md`)을 **한 3D 화면**에 놓고 라인별 상태를 함께 봅니다.

- 열기: 트윈 서버를 켜고 http://localhost:5001/3d/factory (각 3D 화면의 "공장 전체" 링크, 주소 옵션 `?embed=1`, `?embed=view`)
- **전체** 버튼은 두 라인이 모두 보이게 창 크기에 맞춰 카메라를 맞추고, **라인 이름** 버튼은 그 라인으로 확대합니다.
- 왼쪽 카드: 라인별 상태(가동, 정지, AI 이상 감지 경보), 카운트, 처리량, 병목과 **시작, 정지, 리셋** 같은 조작 버튼
- 아래쪽: 시점, 이름표 켜기/끄기, **용어**(현장 용어 / 장비 원명칭) 전환

## 구조

```
src/scenes/machining.json           가공 라인 3D 장면 (tools/make_machining_scene.py 로 만듦)
src/scenes/press_weld_paint.json    프레스 라인 3D 장면
src/scenes/logistics.json           물류 · 출하 구역 3D 장면 (tools/make_logistics_scene.py)
src/scenes/factory.json             라인별 위치(offset), 카메라
/api/factory/state                  라인별 상태를 한 번에 {machining: ..., press: ..., logistics: ...}
src/static/factory.js               위 파일들을 읽어 한 장면에 그리는 범용 뷰어
```

새 라인은 장면 JSON, 상태, `factory.json` 한 줄이면 이 화면에 들어옵니다. 물류 · 출하 구역이 그렇게 들어와 있습니다. 형식은 `scene_format.md`.

## 시험

`python tests\test_factory.py`: 장면 JSON의 모든 path가 서버 상태에 있는지, 가짜 three.js 에서 뷰어를 돌려 두 라인의 배치(offset), 실린더 로드 길이, 부품 위치와 색, 스택 라이트, AI 경보 조명, 요약 카드, 용어 전환을 확인합니다.
(실제 화면 모양은 브라우저에서 확인해야 합니다.)

## 알려진 한계

- 기존 단일 라인 화면(`/3d`, `/3d/line`)은 그대로 두고 있고, 통합 화면과 같은 장면 JSON을 쓰는 쪽으로 합칠 수 있습니다.
- 라인을 클릭해서 확대하는 기능은 버튼으로 대신했습니다.
- 세 구역의 **배치(offset)는 임시값**입니다 (`factory.json`). 실제 공장처럼 공정 구역 사이를 대차, AGV로 잇는 것은 아직 하지 않았습니다.

## MES 공장현황 대시보드

MES 쪽에서 세 구역을 숫자로 보는 페이지는 `dashboard.md`를 보세요 (3D 공장 화면이 위에 들어 있습니다).
