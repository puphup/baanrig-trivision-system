# Trivision Wall — Motor Map & Network Reference

Development reference for the Trivision motor control application.
Project: Louis Vuitton — Visionary Journeys, Bangkok Extension (Trivision Room).

- **Geometry source:** BAANRIG drawing `TRIVISION_ROOM_09052026` (unit positions), `TRIVISION_ROOM_09022026` (cable tables, motor count)
- **System:** 231 motors, 11 control cabinets, one RS-485 bus per cabinet
- **Drives:** STEPPERONLINE iCL-RS integrated closed-loop steppers (Modbus RTU)
- **Document rev:** matches setup document Rev 3 (07/09/2026)

## 1. Network

| Item | Value |
|---|---|
| Subnet | `192.168.20.0/24` |
| Master station (recommended) | `192.168.20.10` |
| Gateway IP pool | `192.168.20.101` – `192.168.20.122` |
| Gateway rule | cabinet *n*: active IP = `192.168.20.(99+2n)` (odd), spare IP = `+1` (even) |
| Modbus TCP port | `502` |
| RS-485 serial | 115,200 bps, 8-N-1 (drive: DIP SW6+SW7 both ON, or Pr5.22 = 6; gateway set to match) |
| Modbus slave ID rule | **restarts at 1 on every gateway/bus**: `modbusId = motor − firstMotorOfCabinet + 1` (1–24 max, settable on drive DIP SW1–SW5) |

A motor is uniquely addressed by the pair (`gatewayIp`, `modbusId`). The wall-wide motor number (1–231, per drawing) is the application key; the table and JSON below map it to the address pair.

## 2. Cabinet / bus map

| Cabinet | Motors | Qty | Modbus IDs | Gateway IP (Bus A) | Spare IP |
|---|---|---|---|---|---|
| 1 | 1 – 21 | 21 | 1 – 21 | `192.168.20.101` | `192.168.20.102` |
| 2 | 22 – 42 | 21 | 1 – 21 | `192.168.20.103` | `192.168.20.104` |
| 3 | 43 – 63 | 21 | 1 – 21 | `192.168.20.105` | `192.168.20.106` |
| 4 | 64 – 84 | 21 | 1 – 21 | `192.168.20.107` | `192.168.20.108` |
| 5 | 85 – 105 | 21 | 1 – 21 | `192.168.20.109` | `192.168.20.110` |
| 6 | 106 – 126 | 21 | 1 – 21 | `192.168.20.111` | `192.168.20.112` |
| 7 | 127 – 137 | 11 | 1 – 11 | `192.168.20.113` | `192.168.20.114` |
| 8 | 138 – 159 | 22 | 1 – 22 | `192.168.20.115` | `192.168.20.116` |
| 9 | 160 – 183 | 24 | 1 – 24 | `192.168.20.117` | `192.168.20.118` |
| 10 | 184 – 207 | 24 | 1 – 24 | `192.168.20.119` | `192.168.20.120` |
| 11 | 208 – 231 | 24 | 1 – 24 | `192.168.20.121` | `192.168.20.122` |
| **Total** | **1 – 231** | **231** | — | 11 active buses | 11 reserved |

Examples: motor 1 → `.101` ID 1 · motor 42 → `.103` ID 21 · motor 160 → `.117` ID 1 · motor 231 → `.121` ID 24.

## 3. Coordinate system

Positions are in the drawing's SVG viewBox space of `TRIVISION_ROOM_09052026` (`viewBox 0 0 3371 2384`, x right, y **down** — standard SVG orientation).

- Content bounding box of the wall: x ≈ 288 – 3060, y ≈ 650 – 1676
- Unit pitch along the wall: **28.65 units = 177 mm** → **1 unit ≈ 6.18 mm**
- `apexDeg`: direction the prism apex points (outward face normal), degrees, SVG convention (0° = +x, positive = clockwise on screen). To render a triangle whose apex points "up" (−y) before rotation, rotate it by `apexDeg + 90`.
- Motor order along the wall: 1 (top-left end of the upper band) → 231 (left end of the lower straight run).

## 4. Data notes

- Motors **133–137** (`"estimated": true`): not present in the 09/05 drawing (it shows only 6 of the 11 Cabinet-7 units). Their positions continue Cabinet 7's arc at the standard pitch (circle fit, R ≈ 241 units, 6.82°/step). Replace these five entries when BAANRIG issues the corrected drawing.
- `cableMm`: per-motor power-cable cut length **including the +500 mm allowance**, from the 09/02 drawing tables (1:1 with this numbering). Boundary motors re-grouped between cabinets (159, 180–183, 205–207) pending length re-confirmation; motor 161's base length (−111 mm) also flagged with BAANRIG. Total 889,134 mm.
- Grouping is the adjusted one (Cabinet 8 = 22, Cabinets 9/10/11 = 24 each); the drawing's original color zones were 21/25/27 for cabinets 9–11.

## 5. Motor data (JSON)

One record per motor, in motor order. Fields: `motor` (wall-wide number), `cabinet`, `modbusId` (per-gateway slave ID, restarts at 1), `gatewayIp`, `x`, `y` (viewBox units), `apexDeg`, `cableMm`, `estimated`.

```json
[{"motor":1,"cabinet":1,"modbusId":1,"gatewayIp":"192.168.20.101","x":287.8,"y":1003.4,"apexDeg":-95.5,"cableMm":6300,"estimated":false},
{"motor":2,"cabinet":1,"modbusId":2,"gatewayIp":"192.168.20.101","x":315.7,"y":997.2,"apexDeg":-109.6,"cableMm":6123,"estimated":false},
{"motor":3,"cabinet":1,"modbusId":3,"gatewayIp":"192.168.20.101","x":341.2,"y":984.4,"apexDeg":-123.6,"cableMm":5946,"estimated":false},
{"motor":4,"cabinet":1,"modbusId":4,"gatewayIp":"192.168.20.101","x":362.9,"y":965.8,"apexDeg":-137.7,"cableMm":5769,"estimated":false},
{"motor":5,"cabinet":1,"modbusId":5,"gatewayIp":"192.168.20.101","x":379.4,"y":942.5,"apexDeg":88.2,"cableMm":5592,"estimated":false},
{"motor":6,"cabinet":1,"modbusId":6,"gatewayIp":"192.168.20.101","x":389.7,"y":915.8,"apexDeg":-165.8,"cableMm":5415,"estimated":false},
{"motor":7,"cabinet":1,"modbusId":7,"gatewayIp":"192.168.20.101","x":393.3,"y":887.5,"apexDeg":-178.0,"cableMm":5238,"estimated":false},
{"motor":8,"cabinet":1,"modbusId":8,"gatewayIp":"192.168.20.101","x":396.0,"y":859.0,"apexDeg":-171.3,"cableMm":5061,"estimated":false},
{"motor":9,"cabinet":1,"modbusId":9,"gatewayIp":"192.168.20.101","x":402.0,"y":831.0,"apexDeg":75.4,"cableMm":4884,"estimated":false},
{"motor":10,"cabinet":1,"modbusId":10,"gatewayIp":"192.168.20.101","x":411.1,"y":803.9,"apexDeg":-158.0,"cableMm":4707,"estimated":false},
{"motor":11,"cabinet":1,"modbusId":11,"gatewayIp":"192.168.20.101","x":423.4,"y":778.0,"apexDeg":-31.3,"cableMm":4530,"estimated":false},
{"motor":12,"cabinet":1,"modbusId":12,"gatewayIp":"192.168.20.101","x":438.6,"y":753.8,"apexDeg":-24.6,"cableMm":4353,"estimated":false},
{"motor":13,"cabinet":1,"modbusId":13,"gatewayIp":"192.168.20.101","x":456.5,"y":731.4,"apexDeg":-17.9,"cableMm":4176,"estimated":false},
{"motor":14,"cabinet":1,"modbusId":14,"gatewayIp":"192.168.20.101","x":476.9,"y":711.3,"apexDeg":-131.3,"cableMm":3999,"estimated":false},
{"motor":15,"cabinet":1,"modbusId":15,"gatewayIp":"192.168.20.101","x":499.5,"y":693.7,"apexDeg":115.4,"cableMm":3822,"estimated":false},
{"motor":16,"cabinet":1,"modbusId":16,"gatewayIp":"192.168.20.101","x":523.9,"y":678.9,"apexDeg":2.1,"cableMm":3645,"estimated":false},
{"motor":17,"cabinet":1,"modbusId":17,"gatewayIp":"192.168.20.101","x":550.0,"y":667.0,"apexDeg":128.8,"cableMm":3468,"estimated":false},
{"motor":18,"cabinet":1,"modbusId":18,"gatewayIp":"192.168.20.101","x":577.2,"y":658.2,"apexDeg":15.4,"cableMm":3291,"estimated":false},
{"motor":19,"cabinet":1,"modbusId":19,"gatewayIp":"192.168.20.101","x":605.3,"y":652.6,"apexDeg":142.1,"cableMm":3114,"estimated":false},
{"motor":20,"cabinet":1,"modbusId":20,"gatewayIp":"192.168.20.101","x":633.8,"y":650.4,"apexDeg":-91.2,"cableMm":2937,"estimated":false},
{"motor":21,"cabinet":1,"modbusId":21,"gatewayIp":"192.168.20.101","x":662.4,"y":651.4,"apexDeg":35.5,"cableMm":2760,"estimated":false},
{"motor":22,"cabinet":2,"modbusId":1,"gatewayIp":"192.168.20.103","x":690.7,"y":655.8,"apexDeg":162.1,"cableMm":5477,"estimated":false},
{"motor":23,"cabinet":2,"modbusId":2,"gatewayIp":"192.168.20.103","x":718.3,"y":663.5,"apexDeg":-71.2,"cableMm":5300,"estimated":false},
{"motor":24,"cabinet":2,"modbusId":3,"gatewayIp":"192.168.20.103","x":744.8,"y":674.3,"apexDeg":175.5,"cableMm":5123,"estimated":false},
{"motor":25,"cabinet":2,"modbusId":4,"gatewayIp":"192.168.20.103","x":769.9,"y":688.1,"apexDeg":-57.8,"cableMm":4946,"estimated":false},
{"motor":26,"cabinet":2,"modbusId":5,"gatewayIp":"192.168.20.103","x":793.2,"y":704.7,"apexDeg":-171.1,"cableMm":4769,"estimated":false},
{"motor":27,"cabinet":2,"modbusId":6,"gatewayIp":"192.168.20.103","x":814.4,"y":723.9,"apexDeg":-164.5,"cableMm":4592,"estimated":false},
{"motor":28,"cabinet":2,"modbusId":7,"gatewayIp":"192.168.20.103","x":833.6,"y":745.1,"apexDeg":74.5,"cableMm":4415,"estimated":false},
{"motor":29,"cabinet":2,"modbusId":8,"gatewayIp":"192.168.20.103","x":857.0,"y":761.4,"apexDeg":55.1,"cableMm":4238,"estimated":false},
{"motor":30,"cabinet":2,"modbusId":9,"gatewayIp":"192.168.20.103","x":884.5,"y":769.0,"apexDeg":35.7,"cableMm":4061,"estimated":false},
{"motor":31,"cabinet":2,"modbusId":10,"gatewayIp":"192.168.20.103","x":913.0,"y":767.0,"apexDeg":136.4,"cableMm":3884,"estimated":false},
{"motor":32,"cabinet":2,"modbusId":11,"gatewayIp":"192.168.20.103","x":939.1,"y":755.7,"apexDeg":117.0,"cableMm":3707,"estimated":false},
{"motor":33,"cabinet":2,"modbusId":12,"gatewayIp":"192.168.20.103","x":960.1,"y":736.4,"apexDeg":100.6,"cableMm":3530,"estimated":false},
{"motor":34,"cabinet":2,"modbusId":13,"gatewayIp":"192.168.20.103","x":980.0,"y":715.8,"apexDeg":-12.8,"cableMm":3353,"estimated":false},
{"motor":35,"cabinet":2,"modbusId":14,"gatewayIp":"192.168.20.103","x":1002.1,"y":697.6,"apexDeg":-6.1,"cableMm":3176,"estimated":false},
{"motor":36,"cabinet":2,"modbusId":15,"gatewayIp":"192.168.20.103","x":1026.2,"y":682.1,"apexDeg":120.6,"cableMm":2999,"estimated":false},
{"motor":37,"cabinet":2,"modbusId":16,"gatewayIp":"192.168.20.103","x":1051.9,"y":669.6,"apexDeg":7.3,"cableMm":2822,"estimated":false},
{"motor":38,"cabinet":2,"modbusId":17,"gatewayIp":"192.168.20.103","x":1078.9,"y":660.1,"apexDeg":133.9,"cableMm":2645,"estimated":false},
{"motor":39,"cabinet":2,"modbusId":18,"gatewayIp":"192.168.20.103","x":1106.8,"y":653.8,"apexDeg":140.6,"cableMm":2468,"estimated":false},
{"motor":40,"cabinet":2,"modbusId":19,"gatewayIp":"192.168.20.103","x":1135.3,"y":650.7,"apexDeg":27.3,"cableMm":2291,"estimated":false},
{"motor":41,"cabinet":2,"modbusId":20,"gatewayIp":"192.168.20.103","x":1163.9,"y":651.1,"apexDeg":154.0,"cableMm":2114,"estimated":false},
{"motor":42,"cabinet":2,"modbusId":21,"gatewayIp":"192.168.20.103","x":1192.3,"y":654.7,"apexDeg":40.7,"cableMm":1937,"estimated":false},
{"motor":43,"cabinet":3,"modbusId":1,"gatewayIp":"192.168.20.105","x":1220.0,"y":661.6,"apexDeg":47.3,"cableMm":6154,"estimated":false},
{"motor":44,"cabinet":3,"modbusId":2,"gatewayIp":"192.168.20.105","x":1246.8,"y":671.7,"apexDeg":54.0,"cableMm":5977,"estimated":false},
{"motor":45,"cabinet":3,"modbusId":3,"gatewayIp":"192.168.20.105","x":1272.3,"y":684.9,"apexDeg":-59.3,"cableMm":5800,"estimated":false},
{"motor":46,"cabinet":3,"modbusId":4,"gatewayIp":"192.168.20.105","x":1296.0,"y":700.9,"apexDeg":67.4,"cableMm":5623,"estimated":false},
{"motor":47,"cabinet":3,"modbusId":5,"gatewayIp":"192.168.20.105","x":1317.7,"y":719.5,"apexDeg":-166.0,"cableMm":5446,"estimated":false},
{"motor":48,"cabinet":3,"modbusId":6,"gatewayIp":"192.168.20.105","x":1336.9,"y":740.8,"apexDeg":-161.1,"cableMm":5269,"estimated":false},
{"motor":49,"cabinet":3,"modbusId":7,"gatewayIp":"192.168.20.105","x":1356.4,"y":761.7,"apexDeg":-164.7,"cableMm":5092,"estimated":false},
{"motor":50,"cabinet":3,"modbusId":8,"gatewayIp":"192.168.20.105","x":1377.1,"y":781.5,"apexDeg":71.8,"cableMm":4915,"estimated":false},
{"motor":51,"cabinet":3,"modbusId":9,"gatewayIp":"192.168.20.105","x":1399.1,"y":799.9,"apexDeg":-51.7,"cableMm":4738,"estimated":false},
{"motor":52,"cabinet":3,"modbusId":10,"gatewayIp":"192.168.20.105","x":1422.1,"y":816.9,"apexDeg":-55.3,"cableMm":4561,"estimated":false},
{"motor":53,"cabinet":3,"modbusId":11,"gatewayIp":"192.168.20.105","x":1446.1,"y":832.5,"apexDeg":-178.8,"cableMm":4384,"estimated":false},
{"motor":54,"cabinet":3,"modbusId":12,"gatewayIp":"192.168.20.105","x":1471.1,"y":846.5,"apexDeg":177.6,"cableMm":4207,"estimated":false},
{"motor":55,"cabinet":3,"modbusId":13,"gatewayIp":"192.168.20.105","x":1496.8,"y":859.0,"apexDeg":174.1,"cableMm":4030,"estimated":false},
{"motor":56,"cabinet":3,"modbusId":14,"gatewayIp":"192.168.20.105","x":1523.3,"y":869.9,"apexDeg":-69.5,"cableMm":3853,"estimated":false},
{"motor":57,"cabinet":3,"modbusId":15,"gatewayIp":"192.168.20.105","x":1550.4,"y":879.1,"apexDeg":47.0,"cableMm":3676,"estimated":false},
{"motor":58,"cabinet":3,"modbusId":16,"gatewayIp":"192.168.20.105","x":1578.0,"y":886.7,"apexDeg":-76.5,"cableMm":3499,"estimated":false},
{"motor":59,"cabinet":3,"modbusId":17,"gatewayIp":"192.168.20.105","x":1606.1,"y":892.5,"apexDeg":-80.1,"cableMm":3322,"estimated":false},
{"motor":60,"cabinet":3,"modbusId":18,"gatewayIp":"192.168.20.105","x":1634.4,"y":896.5,"apexDeg":36.4,"cableMm":3145,"estimated":false},
{"motor":61,"cabinet":3,"modbusId":19,"gatewayIp":"192.168.20.105","x":1663.0,"y":898.8,"apexDeg":-87.2,"cableMm":2968,"estimated":false},
{"motor":62,"cabinet":3,"modbusId":20,"gatewayIp":"192.168.20.105","x":1691.6,"y":899.3,"apexDeg":29.3,"cableMm":2791,"estimated":false},
{"motor":63,"cabinet":3,"modbusId":21,"gatewayIp":"192.168.20.105","x":1720.2,"y":898.1,"apexDeg":145.8,"cableMm":2614,"estimated":false},
{"motor":64,"cabinet":4,"modbusId":1,"gatewayIp":"192.168.20.107","x":1748.7,"y":895.1,"apexDeg":-97.8,"cableMm":6031,"estimated":false},
{"motor":65,"cabinet":4,"modbusId":2,"gatewayIp":"192.168.20.107","x":1776.9,"y":890.4,"apexDeg":-101.3,"cableMm":5854,"estimated":false},
{"motor":66,"cabinet":4,"modbusId":3,"gatewayIp":"192.168.20.107","x":1804.8,"y":883.9,"apexDeg":135.1,"cableMm":5677,"estimated":false},
{"motor":67,"cabinet":4,"modbusId":4,"gatewayIp":"192.168.20.107","x":1832.3,"y":875.7,"apexDeg":-108.4,"cableMm":5500,"estimated":false},
{"motor":68,"cabinet":4,"modbusId":5,"gatewayIp":"192.168.20.107","x":1859.1,"y":865.8,"apexDeg":128.0,"cableMm":5323,"estimated":false},
{"motor":69,"cabinet":4,"modbusId":6,"gatewayIp":"192.168.20.107","x":1885.3,"y":854.3,"apexDeg":4.5,"cableMm":5146,"estimated":false},
{"motor":70,"cabinet":4,"modbusId":7,"gatewayIp":"192.168.20.107","x":1910.8,"y":841.1,"apexDeg":1.0,"cableMm":4969,"estimated":false},
{"motor":71,"cabinet":4,"modbusId":8,"gatewayIp":"192.168.20.107","x":1935.4,"y":826.5,"apexDeg":-2.6,"cableMm":4792,"estimated":false},
{"motor":72,"cabinet":4,"modbusId":9,"gatewayIp":"192.168.20.107","x":1959.0,"y":810.3,"apexDeg":113.9,"cableMm":4615,"estimated":false},
{"motor":73,"cabinet":4,"modbusId":10,"gatewayIp":"192.168.20.107","x":1981.6,"y":792.7,"apexDeg":110.3,"cableMm":4438,"estimated":false},
{"motor":74,"cabinet":4,"modbusId":11,"gatewayIp":"192.168.20.107","x":2003.1,"y":773.8,"apexDeg":-133.2,"cableMm":4261,"estimated":false},
{"motor":75,"cabinet":4,"modbusId":12,"gatewayIp":"192.168.20.107","x":2023.4,"y":753.5,"apexDeg":-16.7,"cableMm":4084,"estimated":false},
{"motor":76,"cabinet":4,"modbusId":13,"gatewayIp":"192.168.20.107","x":2043.0,"y":732.7,"apexDeg":106.9,"cableMm":3907,"estimated":false},
{"motor":77,"cabinet":4,"modbusId":14,"gatewayIp":"192.168.20.107","x":2065.0,"y":714.4,"apexDeg":-126.4,"cableMm":3730,"estimated":false},
{"motor":78,"cabinet":4,"modbusId":15,"gatewayIp":"192.168.20.107","x":2089.0,"y":698.8,"apexDeg":120.3,"cableMm":3553,"estimated":false},
{"motor":79,"cabinet":4,"modbusId":16,"gatewayIp":"192.168.20.107","x":2114.6,"y":686.1,"apexDeg":6.9,"cableMm":3376,"estimated":false},
{"motor":80,"cabinet":4,"modbusId":17,"gatewayIp":"192.168.20.107","x":2141.6,"y":676.4,"apexDeg":-106.4,"cableMm":3199,"estimated":false},
{"motor":81,"cabinet":4,"modbusId":18,"gatewayIp":"192.168.20.107","x":2169.5,"y":670.0,"apexDeg":140.3,"cableMm":3022,"estimated":false},
{"motor":82,"cabinet":4,"modbusId":19,"gatewayIp":"192.168.20.107","x":2197.9,"y":666.8,"apexDeg":-93.0,"cableMm":2845,"estimated":false},
{"motor":83,"cabinet":4,"modbusId":20,"gatewayIp":"192.168.20.107","x":2226.5,"y":666.9,"apexDeg":33.6,"cableMm":2668,"estimated":false},
{"motor":84,"cabinet":4,"modbusId":21,"gatewayIp":"192.168.20.107","x":2254.9,"y":670.4,"apexDeg":-79.7,"cableMm":2491,"estimated":false},
{"motor":85,"cabinet":5,"modbusId":1,"gatewayIp":"192.168.20.109","x":2282.8,"y":677.2,"apexDeg":47.0,"cableMm":3500,"estimated":false},
{"motor":86,"cabinet":5,"modbusId":2,"gatewayIp":"192.168.20.109","x":2309.6,"y":687.1,"apexDeg":173.7,"cableMm":3323,"estimated":false},
{"motor":87,"cabinet":5,"modbusId":3,"gatewayIp":"192.168.20.109","x":2335.1,"y":700.1,"apexDeg":60.3,"cableMm":3146,"estimated":false},
{"motor":88,"cabinet":5,"modbusId":4,"gatewayIp":"192.168.20.109","x":2358.9,"y":716.0,"apexDeg":-53.0,"cableMm":2969,"estimated":false},
{"motor":89,"cabinet":5,"modbusId":5,"gatewayIp":"192.168.20.109","x":2380.7,"y":734.5,"apexDeg":-46.3,"cableMm":2792,"estimated":false},
{"motor":90,"cabinet":5,"modbusId":6,"gatewayIp":"192.168.20.109","x":2400.2,"y":755.4,"apexDeg":80.4,"cableMm":2615,"estimated":false},
{"motor":91,"cabinet":5,"modbusId":7,"gatewayIp":"192.168.20.109","x":2417.2,"y":778.5,"apexDeg":-33.0,"cableMm":2438,"estimated":false},
{"motor":92,"cabinet":5,"modbusId":8,"gatewayIp":"192.168.20.109","x":2431.3,"y":803.4,"apexDeg":-146.3,"cableMm":2261,"estimated":false},
{"motor":93,"cabinet":5,"modbusId":9,"gatewayIp":"192.168.20.109","x":2443.7,"y":829.2,"apexDeg":88.7,"cableMm":2084,"estimated":false},
{"motor":94,"cabinet":5,"modbusId":10,"gatewayIp":"192.168.20.109","x":2460.5,"y":852.3,"apexDeg":-40.9,"cableMm":1907,"estimated":false},
{"motor":95,"cabinet":5,"modbusId":11,"gatewayIp":"192.168.20.109","x":2481.0,"y":872.3,"apexDeg":-170.6,"cableMm":1730,"estimated":false},
{"motor":96,"cabinet":5,"modbusId":12,"gatewayIp":"192.168.20.109","x":2504.6,"y":888.5,"apexDeg":59.8,"cableMm":1553,"estimated":false},
{"motor":97,"cabinet":5,"modbusId":13,"gatewayIp":"192.168.20.109","x":2530.5,"y":900.6,"apexDeg":50.1,"cableMm":1376,"estimated":false},
{"motor":98,"cabinet":5,"modbusId":14,"gatewayIp":"192.168.20.109","x":2558.1,"y":908.1,"apexDeg":40.5,"cableMm":1199,"estimated":false},
{"motor":99,"cabinet":5,"modbusId":15,"gatewayIp":"192.168.20.109","x":2586.5,"y":911.0,"apexDeg":-89.2,"cableMm":1022,"estimated":false},
{"motor":100,"cabinet":5,"modbusId":16,"gatewayIp":"192.168.20.109","x":2615.1,"y":909.0,"apexDeg":141.2,"cableMm":1115,"estimated":false},
{"motor":101,"cabinet":5,"modbusId":17,"gatewayIp":"192.168.20.109","x":2642.9,"y":902.2,"apexDeg":11.5,"cableMm":1292,"estimated":false},
{"motor":102,"cabinet":5,"modbusId":18,"gatewayIp":"192.168.20.109","x":2669.2,"y":890.9,"apexDeg":-118.1,"cableMm":1469,"estimated":false},
{"motor":103,"cabinet":5,"modbusId":19,"gatewayIp":"192.168.20.109","x":2693.5,"y":875.9,"apexDeg":-119.5,"cableMm":1646,"estimated":false},
{"motor":104,"cabinet":5,"modbusId":20,"gatewayIp":"192.168.20.109","x":2719.2,"y":863.3,"apexDeg":7.2,"cableMm":1823,"estimated":false},
{"motor":105,"cabinet":5,"modbusId":21,"gatewayIp":"192.168.20.109","x":2746.2,"y":853.8,"apexDeg":133.9,"cableMm":2000,"estimated":false},
{"motor":106,"cabinet":6,"modbusId":1,"gatewayIp":"192.168.20.111","x":2774.1,"y":847.4,"apexDeg":140.6,"cableMm":4585,"estimated":false},
{"motor":107,"cabinet":6,"modbusId":2,"gatewayIp":"192.168.20.111","x":2802.6,"y":844.4,"apexDeg":147.2,"cableMm":4408,"estimated":false},
{"motor":108,"cabinet":6,"modbusId":3,"gatewayIp":"192.168.20.111","x":2831.2,"y":844.7,"apexDeg":33.9,"cableMm":4231,"estimated":false},
{"motor":109,"cabinet":6,"modbusId":4,"gatewayIp":"192.168.20.111","x":2859.6,"y":848.3,"apexDeg":160.6,"cableMm":4054,"estimated":false},
{"motor":110,"cabinet":6,"modbusId":5,"gatewayIp":"192.168.20.111","x":2887.4,"y":855.2,"apexDeg":47.3,"cableMm":3877,"estimated":false},
{"motor":111,"cabinet":6,"modbusId":6,"gatewayIp":"192.168.20.111","x":2914.2,"y":865.3,"apexDeg":54.0,"cableMm":3700,"estimated":false},
{"motor":112,"cabinet":6,"modbusId":7,"gatewayIp":"192.168.20.111","x":2939.6,"y":878.4,"apexDeg":-179.4,"cableMm":3523,"estimated":false},
{"motor":113,"cabinet":6,"modbusId":8,"gatewayIp":"192.168.20.111","x":2963.3,"y":894.4,"apexDeg":-172.7,"cableMm":3346,"estimated":false},
{"motor":114,"cabinet":6,"modbusId":9,"gatewayIp":"192.168.20.111","x":2985.1,"y":913.1,"apexDeg":74.0,"cableMm":3169,"estimated":false},
{"motor":115,"cabinet":6,"modbusId":10,"gatewayIp":"192.168.20.111","x":3004.5,"y":934.1,"apexDeg":-39.3,"cableMm":2992,"estimated":false},
{"motor":116,"cabinet":6,"modbusId":11,"gatewayIp":"192.168.20.111","x":3021.3,"y":957.2,"apexDeg":-152.7,"cableMm":2815,"estimated":false},
{"motor":117,"cabinet":6,"modbusId":12,"gatewayIp":"192.168.20.111","x":3035.3,"y":982.2,"apexDeg":-26.0,"cableMm":2638,"estimated":false},
{"motor":118,"cabinet":6,"modbusId":13,"gatewayIp":"192.168.20.111","x":3046.3,"y":1008.6,"apexDeg":100.7,"cableMm":2461,"estimated":false},
{"motor":119,"cabinet":6,"modbusId":14,"gatewayIp":"192.168.20.111","x":3054.2,"y":1036.1,"apexDeg":-132.6,"cableMm":2284,"estimated":false},
{"motor":120,"cabinet":6,"modbusId":15,"gatewayIp":"192.168.20.111","x":3058.9,"y":1064.4,"apexDeg":114.0,"cableMm":2107,"estimated":false},
{"motor":121,"cabinet":6,"modbusId":16,"gatewayIp":"192.168.20.111","x":3060.2,"y":1093.0,"apexDeg":120.7,"cableMm":1930,"estimated":false},
{"motor":122,"cabinet":6,"modbusId":17,"gatewayIp":"192.168.20.111","x":3058.1,"y":1121.5,"apexDeg":-112.6,"cableMm":1753,"estimated":false},
{"motor":123,"cabinet":6,"modbusId":18,"gatewayIp":"192.168.20.111","x":3052.8,"y":1149.6,"apexDeg":14.1,"cableMm":1576,"estimated":false},
{"motor":124,"cabinet":6,"modbusId":19,"gatewayIp":"192.168.20.111","x":3044.3,"y":1177.0,"apexDeg":20.7,"cableMm":1399,"estimated":false},
{"motor":125,"cabinet":6,"modbusId":20,"gatewayIp":"192.168.20.111","x":3032.6,"y":1203.1,"apexDeg":-92.6,"cableMm":1222,"estimated":false},
{"motor":126,"cabinet":6,"modbusId":21,"gatewayIp":"192.168.20.111","x":3018.0,"y":1227.7,"apexDeg":154.1,"cableMm":1045,"estimated":false},
{"motor":127,"cabinet":7,"modbusId":1,"gatewayIp":"192.168.20.113","x":3000.6,"y":1250.4,"apexDeg":160.8,"cableMm":2354,"estimated":false},
{"motor":128,"cabinet":7,"modbusId":2,"gatewayIp":"192.168.20.113","x":2980.6,"y":1271.0,"apexDeg":47.4,"cableMm":2177,"estimated":false},
{"motor":129,"cabinet":7,"modbusId":3,"gatewayIp":"192.168.20.113","x":2958.5,"y":1289.1,"apexDeg":-65.9,"cableMm":2000,"estimated":false},
{"motor":130,"cabinet":7,"modbusId":4,"gatewayIp":"192.168.20.113","x":2934.3,"y":1304.5,"apexDeg":60.8,"cableMm":1823,"estimated":false},
{"motor":131,"cabinet":7,"modbusId":5,"gatewayIp":"192.168.20.113","x":2908.6,"y":1317.0,"apexDeg":-172.5,"cableMm":1646,"estimated":false},
{"motor":132,"cabinet":7,"modbusId":6,"gatewayIp":"192.168.20.113","x":2881.5,"y":1326.4,"apexDeg":-45.9,"cableMm":1469,"estimated":false},
{"motor":133,"cabinet":7,"modbusId":7,"gatewayIp":"192.168.20.113","x":2853.5,"y":1332.5,"apexDeg":81.1,"cableMm":1292,"estimated":true},
{"motor":134,"cabinet":7,"modbusId":8,"gatewayIp":"192.168.20.113","x":2824.9,"y":1335.3,"apexDeg":87.9,"cableMm":1469,"estimated":true},
{"motor":135,"cabinet":7,"modbusId":9,"gatewayIp":"192.168.20.113","x":2796.2,"y":1334.6,"apexDeg":94.7,"cableMm":1646,"estimated":true},
{"motor":136,"cabinet":7,"modbusId":10,"gatewayIp":"192.168.20.113","x":2767.9,"y":1330.5,"apexDeg":101.6,"cableMm":1823,"estimated":true},
{"motor":137,"cabinet":7,"modbusId":11,"gatewayIp":"192.168.20.113","x":2740.1,"y":1323.1,"apexDeg":108.4,"cableMm":2000,"estimated":true},
{"motor":138,"cabinet":8,"modbusId":1,"gatewayIp":"192.168.20.115","x":2400.7,"y":1336.6,"apexDeg":-36.0,"cableMm":2600,"estimated":false},
{"motor":139,"cabinet":8,"modbusId":2,"gatewayIp":"192.168.20.115","x":2372.9,"y":1342.9,"apexDeg":-169.6,"cableMm":2423,"estimated":false},
{"motor":140,"cabinet":8,"modbusId":3,"gatewayIp":"192.168.20.115","x":2347.4,"y":1355.6,"apexDeg":56.8,"cableMm":2246,"estimated":false},
{"motor":141,"cabinet":8,"modbusId":4,"gatewayIp":"192.168.20.115","x":2325.5,"y":1373.9,"apexDeg":43.2,"cableMm":2069,"estimated":false},
{"motor":142,"cabinet":8,"modbusId":5,"gatewayIp":"192.168.20.115","x":2308.6,"y":1396.9,"apexDeg":149.6,"cableMm":1892,"estimated":false},
{"motor":143,"cabinet":8,"modbusId":6,"gatewayIp":"192.168.20.115","x":2297.6,"y":1423.2,"apexDeg":-104.0,"cableMm":1715,"estimated":false},
{"motor":144,"cabinet":8,"modbusId":7,"gatewayIp":"192.168.20.115","x":2292.9,"y":1451.3,"apexDeg":4.8,"cableMm":1538,"estimated":false},
{"motor":145,"cabinet":8,"modbusId":8,"gatewayIp":"192.168.20.115","x":2288.9,"y":1479.6,"apexDeg":131.5,"cableMm":1361,"estimated":false},
{"motor":146,"cabinet":8,"modbusId":9,"gatewayIp":"192.168.20.115","x":2281.6,"y":1507.2,"apexDeg":18.1,"cableMm":1184,"estimated":false},
{"motor":147,"cabinet":8,"modbusId":10,"gatewayIp":"192.168.20.115","x":2271.1,"y":1533.8,"apexDeg":24.8,"cableMm":1199,"estimated":false},
{"motor":148,"cabinet":8,"modbusId":11,"gatewayIp":"192.168.20.115","x":2257.6,"y":1558.9,"apexDeg":151.5,"cableMm":1376,"estimated":false},
{"motor":149,"cabinet":8,"modbusId":12,"gatewayIp":"192.168.20.115","x":2241.3,"y":1582.4,"apexDeg":-81.9,"cableMm":1553,"estimated":false},
{"motor":150,"cabinet":8,"modbusId":13,"gatewayIp":"192.168.20.115","x":2222.4,"y":1603.8,"apexDeg":164.8,"cableMm":1730,"estimated":false},
{"motor":151,"cabinet":8,"modbusId":14,"gatewayIp":"192.168.20.115","x":2201.2,"y":1622.9,"apexDeg":-68.6,"cableMm":1907,"estimated":false},
{"motor":152,"cabinet":8,"modbusId":15,"gatewayIp":"192.168.20.115","x":2177.8,"y":1639.4,"apexDeg":-61.9,"cableMm":2084,"estimated":false},
{"motor":153,"cabinet":8,"modbusId":16,"gatewayIp":"192.168.20.115","x":2152.8,"y":1653.0,"apexDeg":-55.2,"cableMm":2261,"estimated":false},
{"motor":154,"cabinet":8,"modbusId":17,"gatewayIp":"192.168.20.115","x":2126.3,"y":1663.7,"apexDeg":-48.6,"cableMm":2438,"estimated":false},
{"motor":155,"cabinet":8,"modbusId":18,"gatewayIp":"192.168.20.115","x":2098.7,"y":1671.2,"apexDeg":-161.9,"cableMm":2615,"estimated":false},
{"motor":156,"cabinet":8,"modbusId":19,"gatewayIp":"192.168.20.115","x":2070.5,"y":1675.4,"apexDeg":-155.3,"cableMm":2792,"estimated":false},
{"motor":157,"cabinet":8,"modbusId":20,"gatewayIp":"192.168.20.115","x":2041.9,"y":1676.4,"apexDeg":-28.6,"cableMm":2969,"estimated":false},
{"motor":158,"cabinet":8,"modbusId":21,"gatewayIp":"192.168.20.115","x":2013.4,"y":1674.1,"apexDeg":-21.9,"cableMm":3146,"estimated":false},
{"motor":159,"cabinet":8,"modbusId":22,"gatewayIp":"192.168.20.115","x":1985.4,"y":1668.4,"apexDeg":-15.3,"cableMm":743,"estimated":false},
{"motor":160,"cabinet":9,"modbusId":1,"gatewayIp":"192.168.20.117","x":1958.3,"y":1659.6,"apexDeg":-128.6,"cableMm":566,"estimated":false},
{"motor":161,"cabinet":9,"modbusId":2,"gatewayIp":"192.168.20.117","x":1932.3,"y":1647.6,"apexDeg":-2.0,"cableMm":389,"estimated":false},
{"motor":162,"cabinet":9,"modbusId":3,"gatewayIp":"192.168.20.117","x":1908.0,"y":1632.8,"apexDeg":4.7,"cableMm":566,"estimated":false},
{"motor":163,"cabinet":9,"modbusId":4,"gatewayIp":"192.168.20.117","x":1885.5,"y":1615.2,"apexDeg":131.4,"cableMm":743,"estimated":false},
{"motor":164,"cabinet":9,"modbusId":5,"gatewayIp":"192.168.20.117","x":1865.1,"y":1595.1,"apexDeg":18.0,"cableMm":920,"estimated":false},
{"motor":165,"cabinet":9,"modbusId":6,"gatewayIp":"192.168.20.117","x":1847.3,"y":1572.8,"apexDeg":144.7,"cableMm":1097,"estimated":false},
{"motor":166,"cabinet":9,"modbusId":7,"gatewayIp":"192.168.20.117","x":1832.2,"y":1548.5,"apexDeg":-88.7,"cableMm":1274,"estimated":false},
{"motor":167,"cabinet":9,"modbusId":8,"gatewayIp":"192.168.20.117","x":1820.0,"y":1522.7,"apexDeg":38.0,"cableMm":1451,"estimated":false},
{"motor":168,"cabinet":9,"modbusId":9,"gatewayIp":"192.168.20.117","x":1810.8,"y":1495.7,"apexDeg":44.7,"cableMm":1628,"estimated":false},
{"motor":169,"cabinet":9,"modbusId":10,"gatewayIp":"192.168.20.117","x":1804.9,"y":1467.7,"apexDeg":-68.7,"cableMm":1805,"estimated":false},
{"motor":170,"cabinet":9,"modbusId":11,"gatewayIp":"192.168.20.117","x":1802.2,"y":1439.3,"apexDeg":178.0,"cableMm":1982,"estimated":false},
{"motor":171,"cabinet":9,"modbusId":12,"gatewayIp":"192.168.20.117","x":1802.0,"y":1410.7,"apexDeg":180.0,"cableMm":2159,"estimated":false},
{"motor":172,"cabinet":9,"modbusId":13,"gatewayIp":"192.168.20.117","x":1802.0,"y":1382.1,"apexDeg":60.0,"cableMm":2336,"estimated":false},
{"motor":173,"cabinet":9,"modbusId":14,"gatewayIp":"192.168.20.117","x":1802.0,"y":1353.6,"apexDeg":-60.0,"cableMm":2513,"estimated":false},
{"motor":174,"cabinet":9,"modbusId":15,"gatewayIp":"192.168.20.117","x":1800.0,"y":1325.1,"apexDeg":51.0,"cableMm":2690,"estimated":false},
{"motor":175,"cabinet":9,"modbusId":16,"gatewayIp":"192.168.20.117","x":1793.1,"y":1297.4,"apexDeg":161.1,"cableMm":2867,"estimated":false},
{"motor":176,"cabinet":9,"modbusId":17,"gatewayIp":"192.168.20.117","x":1781.6,"y":1271.3,"apexDeg":-88.8,"cableMm":3044,"estimated":false},
{"motor":177,"cabinet":9,"modbusId":18,"gatewayIp":"192.168.20.117","x":1765.7,"y":1247.6,"apexDeg":21.3,"cableMm":3221,"estimated":false},
{"motor":178,"cabinet":9,"modbusId":19,"gatewayIp":"192.168.20.117","x":1746.0,"y":1226.9,"apexDeg":131.3,"cableMm":3398,"estimated":false},
{"motor":179,"cabinet":9,"modbusId":20,"gatewayIp":"192.168.20.117","x":1723.0,"y":1210.0,"apexDeg":121.4,"cableMm":3575,"estimated":false},
{"motor":180,"cabinet":9,"modbusId":21,"gatewayIp":"192.168.20.117","x":1697.4,"y":1197.3,"apexDeg":-8.5,"cableMm":3752,"estimated":false},
{"motor":181,"cabinet":9,"modbusId":22,"gatewayIp":"192.168.20.117","x":1670.1,"y":1189.2,"apexDeg":-18.4,"cableMm":3929,"estimated":false},
{"motor":182,"cabinet":9,"modbusId":23,"gatewayIp":"192.168.20.117","x":1641.7,"y":1185.9,"apexDeg":-148.4,"cableMm":4106,"estimated":false},
{"motor":183,"cabinet":9,"modbusId":24,"gatewayIp":"192.168.20.117","x":1613.2,"y":1187.6,"apexDeg":-38.3,"cableMm":4283,"estimated":false},
{"motor":184,"cabinet":10,"modbusId":1,"gatewayIp":"192.168.20.119","x":1585.4,"y":1194.1,"apexDeg":71.8,"cableMm":4460,"estimated":false},
{"motor":185,"cabinet":10,"modbusId":2,"gatewayIp":"192.168.20.119","x":1559.2,"y":1205.4,"apexDeg":-178.1,"cableMm":4637,"estimated":false},
{"motor":186,"cabinet":10,"modbusId":3,"gatewayIp":"192.168.20.119","x":1535.3,"y":1220.9,"apexDeg":171.9,"cableMm":4814,"estimated":false},
{"motor":187,"cabinet":10,"modbusId":4,"gatewayIp":"192.168.20.119","x":1514.4,"y":1240.4,"apexDeg":42.0,"cableMm":4991,"estimated":false},
{"motor":188,"cabinet":10,"modbusId":5,"gatewayIp":"192.168.20.119","x":1497.1,"y":1263.1,"apexDeg":-84.6,"cableMm":5168,"estimated":false},
{"motor":189,"cabinet":10,"modbusId":6,"gatewayIp":"192.168.20.119","x":1478.3,"y":1284.6,"apexDeg":167.0,"cableMm":5345,"estimated":false},
{"motor":190,"cabinet":10,"modbusId":7,"gatewayIp":"192.168.20.119","x":1455.6,"y":1301.9,"apexDeg":178.6,"cableMm":5522,"estimated":false},
{"motor":191,"cabinet":10,"modbusId":8,"gatewayIp":"192.168.20.119","x":1429.9,"y":1314.2,"apexDeg":-169.8,"cableMm":5699,"estimated":false},
{"motor":192,"cabinet":10,"modbusId":9,"gatewayIp":"192.168.20.119","x":1402.2,"y":1321.1,"apexDeg":81.8,"cableMm":5876,"estimated":false},
{"motor":193,"cabinet":10,"modbusId":10,"gatewayIp":"192.168.20.119","x":1373.7,"y":1322.6,"apexDeg":90.0,"cableMm":6053,"estimated":false},
{"motor":194,"cabinet":10,"modbusId":11,"gatewayIp":"192.168.20.119","x":1345.1,"y":1322.6,"apexDeg":90.0,"cableMm":6230,"estimated":false},
{"motor":195,"cabinet":10,"modbusId":12,"gatewayIp":"192.168.20.119","x":1316.6,"y":1322.6,"apexDeg":90.0,"cableMm":6407,"estimated":false},
{"motor":196,"cabinet":10,"modbusId":13,"gatewayIp":"192.168.20.119","x":1288.0,"y":1322.6,"apexDeg":90.0,"cableMm":6584,"estimated":false},
{"motor":197,"cabinet":10,"modbusId":14,"gatewayIp":"192.168.20.119","x":1259.4,"y":1322.6,"apexDeg":-30.0,"cableMm":6761,"estimated":false},
{"motor":198,"cabinet":10,"modbusId":15,"gatewayIp":"192.168.20.119","x":1230.8,"y":1322.6,"apexDeg":90.0,"cableMm":6938,"estimated":false},
{"motor":199,"cabinet":10,"modbusId":16,"gatewayIp":"192.168.20.119","x":1202.2,"y":1322.6,"apexDeg":90.0,"cableMm":7115,"estimated":false},
{"motor":200,"cabinet":10,"modbusId":17,"gatewayIp":"192.168.20.119","x":1173.7,"y":1322.6,"apexDeg":-150.0,"cableMm":7292,"estimated":false},
{"motor":201,"cabinet":10,"modbusId":18,"gatewayIp":"192.168.20.119","x":1145.1,"y":1322.6,"apexDeg":90.0,"cableMm":7469,"estimated":false},
{"motor":202,"cabinet":10,"modbusId":19,"gatewayIp":"192.168.20.119","x":1116.5,"y":1322.6,"apexDeg":90.0,"cableMm":7646,"estimated":false},
{"motor":203,"cabinet":10,"modbusId":20,"gatewayIp":"192.168.20.119","x":1087.9,"y":1322.6,"apexDeg":90.0,"cableMm":7823,"estimated":false},
{"motor":204,"cabinet":10,"modbusId":21,"gatewayIp":"192.168.20.119","x":1059.4,"y":1322.6,"apexDeg":90.0,"cableMm":8000,"estimated":false},
{"motor":205,"cabinet":10,"modbusId":22,"gatewayIp":"192.168.20.119","x":1030.8,"y":1322.6,"apexDeg":90.0,"cableMm":4498,"estimated":false},
{"motor":206,"cabinet":10,"modbusId":23,"gatewayIp":"192.168.20.119","x":1002.2,"y":1322.6,"apexDeg":90.0,"cableMm":4675,"estimated":false},
{"motor":207,"cabinet":10,"modbusId":24,"gatewayIp":"192.168.20.119","x":973.6,"y":1322.6,"apexDeg":90.0,"cableMm":4852,"estimated":false},
{"motor":208,"cabinet":11,"modbusId":1,"gatewayIp":"192.168.20.121","x":945.0,"y":1322.6,"apexDeg":90.0,"cableMm":5029,"estimated":false},
{"motor":209,"cabinet":11,"modbusId":2,"gatewayIp":"192.168.20.121","x":916.5,"y":1322.6,"apexDeg":90.0,"cableMm":5206,"estimated":false},
{"motor":210,"cabinet":11,"modbusId":3,"gatewayIp":"192.168.20.121","x":887.9,"y":1322.6,"apexDeg":-150.0,"cableMm":5383,"estimated":false},
{"motor":211,"cabinet":11,"modbusId":4,"gatewayIp":"192.168.20.121","x":859.3,"y":1322.6,"apexDeg":90.0,"cableMm":5560,"estimated":false},
{"motor":212,"cabinet":11,"modbusId":5,"gatewayIp":"192.168.20.121","x":830.7,"y":1322.6,"apexDeg":90.0,"cableMm":5737,"estimated":false},
{"motor":213,"cabinet":11,"modbusId":6,"gatewayIp":"192.168.20.121","x":802.2,"y":1322.6,"apexDeg":-30.0,"cableMm":5914,"estimated":false},
{"motor":214,"cabinet":11,"modbusId":7,"gatewayIp":"192.168.20.121","x":773.6,"y":1322.6,"apexDeg":90.0,"cableMm":6091,"estimated":false},
{"motor":215,"cabinet":11,"modbusId":8,"gatewayIp":"192.168.20.121","x":745.0,"y":1322.6,"apexDeg":90.0,"cableMm":6268,"estimated":false},
{"motor":216,"cabinet":11,"modbusId":9,"gatewayIp":"192.168.20.121","x":716.4,"y":1322.6,"apexDeg":90.0,"cableMm":6445,"estimated":false},
{"motor":217,"cabinet":11,"modbusId":10,"gatewayIp":"192.168.20.121","x":687.8,"y":1322.6,"apexDeg":90.0,"cableMm":6622,"estimated":false},
{"motor":218,"cabinet":11,"modbusId":11,"gatewayIp":"192.168.20.121","x":659.3,"y":1322.6,"apexDeg":90.0,"cableMm":6799,"estimated":false},
{"motor":219,"cabinet":11,"modbusId":12,"gatewayIp":"192.168.20.121","x":630.7,"y":1322.6,"apexDeg":90.0,"cableMm":6976,"estimated":false},
{"motor":220,"cabinet":11,"modbusId":13,"gatewayIp":"192.168.20.121","x":602.1,"y":1322.6,"apexDeg":90.0,"cableMm":7153,"estimated":false},
{"motor":221,"cabinet":11,"modbusId":14,"gatewayIp":"192.168.20.121","x":573.5,"y":1322.6,"apexDeg":90.0,"cableMm":7330,"estimated":false},
{"motor":222,"cabinet":11,"modbusId":15,"gatewayIp":"192.168.20.121","x":544.9,"y":1322.6,"apexDeg":90.0,"cableMm":7507,"estimated":false},
{"motor":223,"cabinet":11,"modbusId":16,"gatewayIp":"192.168.20.121","x":516.4,"y":1322.6,"apexDeg":-150.0,"cableMm":7684,"estimated":false},
{"motor":224,"cabinet":11,"modbusId":17,"gatewayIp":"192.168.20.121","x":487.8,"y":1322.6,"apexDeg":90.0,"cableMm":7861,"estimated":false},
{"motor":225,"cabinet":11,"modbusId":18,"gatewayIp":"192.168.20.121","x":459.2,"y":1322.6,"apexDeg":90.0,"cableMm":8038,"estimated":false},
{"motor":226,"cabinet":11,"modbusId":19,"gatewayIp":"192.168.20.121","x":430.6,"y":1322.6,"apexDeg":-150.0,"cableMm":8215,"estimated":false},
{"motor":227,"cabinet":11,"modbusId":20,"gatewayIp":"192.168.20.121","x":402.1,"y":1322.6,"apexDeg":90.0,"cableMm":8392,"estimated":false},
{"motor":228,"cabinet":11,"modbusId":21,"gatewayIp":"192.168.20.121","x":373.5,"y":1322.6,"apexDeg":90.0,"cableMm":8569,"estimated":false},
{"motor":229,"cabinet":11,"modbusId":22,"gatewayIp":"192.168.20.121","x":344.9,"y":1322.6,"apexDeg":90.0,"cableMm":8746,"estimated":false},
{"motor":230,"cabinet":11,"modbusId":23,"gatewayIp":"192.168.20.121","x":316.3,"y":1322.6,"apexDeg":90.0,"cableMm":8923,"estimated":false},
{"motor":231,"cabinet":11,"modbusId":24,"gatewayIp":"192.168.20.121","x":287.7,"y":1322.6,"apexDeg":90.0,"cableMm":9100,"estimated":false}]
```

## 6. Quick lookups

```
cabinet(m)    = the row of Section 2 whose range contains m
gatewayIp(m)  = 192.168.20.(99 + 2*cabinet(m))
modbusId(m)   = m - firstMotor(cabinet(m)) + 1
mm(x_units)   = x_units * 6.178   // approx, from 28.65 units = 177 mm pitch
```
