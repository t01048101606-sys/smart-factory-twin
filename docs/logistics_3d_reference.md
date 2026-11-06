# 물류 · 출하 구역 3D 디테일링: 조사 자료와 모델링 근거

물류 구역의 3D 모델(`src/scenes/logistics.json`, 생성 스크립트 `tools/make_logistics_scene.py`)을 실제 현장 설비에 가깝게 만들기 위해 웹에서 조사한 자료입니다.
실제 설비 사진이 없어서 규격서, 제조사 카탈로그, 설계 가이드의 수치를 근거로 했습니다. 단위는 미터에 가깝고, 상자와 원기둥을 조합한 모델링입니다 (CAD 가져오기 아님).

## 1. 조사한 수치와 반영

| 항목 | 조사된 값 | 모델에 반영 |
|---|---|---|
| 도크 높이 | 북미 표준 48인치(약 1.2m), 범위 44~55인치. 트럭 적재함 높이와 맞춘다 [1][2][3] | 건물 바닥(도크)을 마당보다 **1.08m 높게** |
| 한국 5톤 트럭 적재함 높이 | 현대 마이티 5톤 카고 **상면지상고 1,050~1,080mm** [8] | 도크 높이 1.08m의 근거 |
| 5톤 카고 적재함 | 마이티 5.1톤 카고 내측 **5,500 x 2,280 x 400mm** (장 x 폭 x 고), 전폭 2.06~2.25m [8][9] | 출하 트럭: 적재함 5.5 x 2.28m, 사이드 보드 0.4m |
| 5톤 탑차/윙바디 | 적재함 **6,800 x 2,300 x 2,300mm** (중고 5톤 윙바디 매물 제원), 17톤 윙바디는 7,000 x 2,350 x 2,300 [10][11] | 입고 트럭: 탑차 적재함 6.8 x 2.3 x 2.3m, 뒷문 양쪽 개방 |
| 도크 문 | 폭 8ft x 높이 9~10ft(약 2.4 x 2.7~3.0m), 트럭이 넓어져 9~10ft 폭 권장 [6][7] | 문 2.6 x 3.0m, 셔터식 (트럭이 붙으면 올라감) |
| 도크 레벨러 | 폭 6~6.5ft(1.8~2.0m), 길이 6/8/10ft, **립 길이 16인치**, 트럭 적재함에 **최소 4~6인치 접촉** [1][5][12] | 판 2.0 x 2.2m, 접히는 립 0.45m가 적재함 위에 **0.23m** 걸침 |
| 도크 구성 | 도크 문, 레벨러, 도크 쉘터/씰, 범퍼, 차량 고정장치, 신호등 [10] | 문 틀, 쉘터, 범퍼(0.22m 돌출), 적/녹 도크 신호등 |
| 후진 접안 | 트럭은 **뒷문(적재함 뒤끝)을 도크에 붙인다**. 레벨러가 높이 차를 흡수 [1][10] | 두 트럭 모두 후진해서 뒤끝이 범퍼에 닿음 (입고 트럭은 이전에 운전석이 도크를 향하던 오류 수정) |
| 파렛트 | 한국 표준 **T-11 1,100 x 1,100mm**, T-12 1,200 x 1,000mm (KS T 1002) [13][14] | 파렛트 1.1 x 1.1m |
| 플라스틱 파렛트 | 1,100 x 1,100 x **높이 150mm**, 러너 3개, 발 9개 [15] | 데크 + 러너 3개, 높이 0.15m, 위에 박스 최대 5개 (수량만큼 표시) |
| AGV | 저상 플랫폼형 1,750 x 970mm, 높이 350~400mm(리프트 포함), 안전 라이다, 비상정지 버튼, **LED 상태 띠**, 속도 1.2~1.5m/s [16][17][18] | 파렛트 잭형 AGV: 구동부 0.8 x 0.72m, 포크 1.15m, 라이다, **경고 비콘(움직이면 깜박임)**, LED 띠(상태 색), 비상정지, 파렛트를 들면 포크 0.1m 상승 |
| 파렛트 랙 | 선택형 랙: 프레임 깊이 = 파렛트 깊이 - 6인치, 단 높이 = 하중 높이 + 4~6인치 여유 + 빔 높이(4인치), 빔 폭 = 파렛트 + 양끝 5인치 + 사이 6인치 [19][20][21] | 업라이트 2.7m + 빔(2.3m 베이), 파렛트 위 자재 높이 = 재고 비율, 재고 램프 |
| 박스 상하차 지그 | **신축(텔레스코픽) 벨트/롤러 컨베이어**가 도크에서 트레일러 안으로 뻗어 박스를 직접 주고받는다. 중첩 구간이 미끄러져 나오고, 박스, 소형 파렛트용 [22][23][24][25] | 입고: 신축 컨베이어 3구간이 1.5초에 걸쳐 트럭 안으로 뻗고, 박스 4개가 흘러오고, 끝나기 전에 접힘 |
| 파렛트 상하차 | 파렛트는 도크 레벨러와 지게차/AGV로 넣는다. 레벨러가 있으면 적재함 바닥과 도크 바닥이 같은 높이 [1][10][25] | 출하: 파렛트가 레벨러 위를 **수평으로** 트럭 적재함에 들어감 (이전에는 비스듬히 올라갔음) |

### 모델에 반영하면서 고친 오류
1. **입고 트럭이 운전석 쪽으로 도크에 접근**하던 것 -> 적재함 뒷문이 도크 쪽 (후진 접안)
2. **도크 바닥과 트럭 바닥의 높이 차이가 없고, 파렛트가 비스듬히 올라가며 트럭에 들어가던 것** -> 도크 높이 1.08m, 적재함 바닥 = 도크 바닥, 수평 이동
3. 파렛트 폭이 1.3m(실제 T-11은 1.1m)이고 트럭 폭 안에 들어가지 않던 것 -> 1.1m, 적재함 폭 2.28m 안에 2개

## 2. 동작과 상태

시뮬레이터(`logistics_sim.py`)가 장면에 내보내는 값(`state()`):
- `inbound`: `truck`(0~1 위치), `moving`(바퀴), `docked`(레벨러 립, 신호등), `door`(뒷문, 셔터), `boom`(신축 컨베이어), `cartons`(박스 4개의 진행도 `p`와 표시 `on`)
- `outbound`: `truck`, `moving`, `docked` (테일게이트가 눕고, 립이 내려오고, 셔터가 올라감)
- `agv`: `pos`, `state`(LED 띠 색), `moving`(경고 비콘), `lift`(포크 상승)
- `parts`: 파렛트 위치, `qty`(박스 수), `stage`

## 3. 시험으로 확인한 것

- `tests/test_logistics.py`: 도크 높이 1.08, 트럭 규격, **적재함 바닥 = 도크 바닥**, 파렛트 아래면이 바닥에 닿음, **트럭 뒤끝 = 범퍼 바깥면(차이 0)**, 레벨러 립 걸침 0.23m, 출하 도크 칸이 레벨러 위, 트럭 안 파렛트가 적재함 폭 안, 신축 컨베이어가 트럭 안에 들어감
- `tests/test_factory.py`: 뷰어에서 트럭 위치, **바퀴 회전(움직일 때만)**, 뒷문 각도, 레벨러 립 각도, 신축 구간 위치, 박스 흐름, AGV 포크 높이, 파렛트 박스 수, 재고 막대가 상태와 일치

## 4. 아직 반영하지 못한 것 (한계)

- **AGV 경로가 단순화**되어 있습니다. 실제 파렛트 잭형 AGV는 칸마다 접근해서 포크를 넣지만, 여기서는 한 직선을 오가고 파렛트가 칸에서 AGV 위치로 미끄러져 옮겨집니다.
- 출하 파렛트가 레벨러에서 트럭 안으로 **미끄러져** 들어갑니다. 실제로는 지게차나 AGV가 트럭 안으로 들어가 내려놓습니다.
- 입고 박스는 신축 컨베이어를 따라 흐르다 검수 컨베이어 끝에서 사라지고, 재고 막대가 올라갑니다. 박스가 랙 파렛트에 쌓이는 과정은 표현하지 않습니다.
- 5톤 윙바디의 날개(양옆으로 열리는 지붕)는 표현하지 않았고, 뒷문만 열립니다. 트럭 바퀴는 굴러가지만 서스펜션, 조향은 없습니다.
- 지게차, 작업자, 도크 휠초크(바퀴 고정), 차량 고정장치는 아직 없습니다.
- 5톤 탑차(6,800 x 2,300 x 2,300mm) 제원은 한 중고 차량 매물의 값이라서, 제조사 공식 제원이 아닙니다 (같은 급의 마이티 카고와 윙바디 제원은 공식 자료).

## 출처

[1] https://projul.com/blog/construction-loading-dock-design-guide/ (도크 높이 48인치, 레벨러 폭, 8ft 문)
[2] https://www.minercorp.com/?p=25491 (도크 높이 44~55인치)
[3] https://www.pentalift.com/?p=3931 (트럭 적재함 46~52인치, 표준 도크 48~50인치)
[4] https://upsideinnovations.com/blog/loading-dock-heights-by-truck-type/ (트럭 종류별 적재함 높이)
[5] https://bluegiant.com/Blue-Giant-Solutions-Leveler-Dimensions.aspx (립 길이 16인치, 접촉 4~6인치)
[6] https://rets.ai/glossary/dock-high-door (도크 문 8 x 9ft)
[7] https://www.bahrns.com/blog/?p=7843 (문 높이 10ft, 트럭별 적재함 높이)
[8] https://www.hyundai.com/ccontents/carmng/CP00000003/mighty-2026-08-spec.pdf (마이티 제원, 상면지상고)
[9] https://www.carnoon.co.kr/newcar/vehicle/11753-115969 (마이티 5.1톤 카고 5,500 x 2,280 x 400)
[10] https://m.cafe.daum.net/jiwooparty/X1Eo/102?svc=AXZ (5톤 윙바디 적재함 6,800 x 2,300 x 2,300, 중고 매물)
[11] https://www.carnoon.co.kr/newcar/vehicle/11003-116035 (17톤 윙바디 7,000 x 2,350 x 2,300)
[12] https://www.pentalift.com/solutions_category/mechanical-size-and-capacity-options/ (레벨러 길이 6, 8, 10ft)
[13] https://koreascience.kr/article/JAKO201317054958710.pdf (T-11 1,100 x 1,100, T-12 1,200 x 1,000, KS T 1002)
[14] https://koreascience.kr/article/JAKO201259149935384.pdf (한국 파렛트 사용 실태)
[15] https://www.hellopro.fr/palette-plastique-medium-1100x1100x150-mm-plateau-ajoure-3-semelles-1002263-6671378-produit.html (1100 x 1100 x 150, 러너 3개)
[16] https://oldwebsite.industrialautomationindia.in/productsitm/16857/AGV-Platform,-PF3/products (저상 AGV 플랫폼 1750 x 970, LED 띠, 스캐너, 비상정지)
[17] https://www.scribd.com/document/731955707/VisionNav-Product-Catalog (파렛트 잭 AGV, 경고등, 범퍼, 라이다)
[18] https://en.ant-robots.com/fdd14-laser-slam-pallet-stacking-agv.html (AGV 속도 1.2~1.5m/s, 안전 구성)
[19] https://www.cisco-eagle.com/uploads/SK-General-Rack/RackDesignGuide.pdf (랙 프레임 깊이, 단 높이)
[20] https://www.wprpwholesalepalletrack.com/?p=912 (랙 폭, 깊이, 여유)
[21] https://rmhsystems.com/?p=29378 (단 사이 간격 계산)
[22] https://www.cisco-eagle.com/blog/wp-json/wp/v2/posts/14430 (신축 컨베이어, 도크와 트레일러 사이)
[23] https://www.mhlnews.com/labor-management/telescopic-conveyor-helps-spot-dock-improvements (신축 컨베이어 작동)
[24] https://fmhconveyors.com/products/telescopic-conveyors/ (신축 컨베이어 제품)
[25] https://racklify.com/encyclopedia/telescopic-conveyor-vs-dock-plate-how-to-choose-the-right-trailer-loading-equipment/ (신축 컨베이어와 레벨러, 리프트 비교)
