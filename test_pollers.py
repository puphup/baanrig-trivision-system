"""Poller fills status_cache; _read_one_status applies zero offset. Run: ./venv/bin/python test_pollers.py"""
import asyncio
from app import server as S
from app.drivers.sim import SimDriver
from app.motor_sim import MotorSim


async def main():
    sim = MotorSim(slave_id=1); sim.position = 4000.0
    S.drivers = {"gw1.1": SimDriver(sim)}
    S.config = {"mode": "simulation", "gateways": [{"id": "gw1", "host": "x", "port": 1}],
                "motors": [{"gateway": "gw1", "slave_id": 1, "driver_type": "icl_rs"}],
                "motor_extras": {"gw1.1": {"motor": 1, "label": "M001", "cabinet": 1, "x": 1.0, "y": 2.0, "apex_deg": -90.0, "estimated": False}}}
    S.zero_offsets = {"gw1.1": 1000}
    await S._start_pollers()
    await asyncio.sleep(0.3)
    assert S.status_cache["gw1.1"]["position_pulses"] == 4000
    st = await S._read_one_status("gw1.1")
    assert st["position_pulses"] == 3000 and st["current_face"] is not None
    assert (await S._read_one_status("nope"))["offline"] is True
    data = await S._build_status()
    inv = data["inventory"][0]
    assert inv["label"] == "M001" and inv["motor"] == 1 and inv["cabinet"] == 1 and inv["apex_deg"] == -90.0
    tasks = list(S._poll_tasks)
    await S._stop_pollers()
    assert tasks and all(t.done() for t in tasks)

    # --- seek-home by cabinet + wall homing resets face, commission on sim fails cleanly
    sim2 = MotorSim(slave_id=1); sim2.position = 777.0
    S.drivers["gw2.1"] = SimDriver(sim2)
    S.config["gateways"].append({"id": "gw2", "host": "y", "port": 1})
    S.config["motors"].append({"gateway": "gw2", "slave_id": 1, "driver_type": "icl_rs"})
    S.config["motor_extras"]["gw2.1"] = {"motor": 2, "label": "M002", "cabinet": 2, "x": 3.0, "y": 4.0, "apex_deg": 0.0, "estimated": False}
    await S._start_pollers()
    r = await S.seek_home(S.SeekHomeRequest(cabinet=2))
    assert r == {"ok": True, "total": 1}, r
    await asyncio.sleep(1.8)                       # 1 s settle + poll in _zero_display_after_homing
    assert sim2.position == 0.0 and sim.position == 4000.0
    assert S.homing_state["done"] == 1 and not S.homing_state["active"]
    await S.show.set_current_page(3)
    r = await S.seek_home(S.SeekHomeRequest())
    assert r["total"] == 2
    await asyncio.sleep(2.0)
    assert S.show.state()["current_page"] == 1
    c = await S.commission(S.CabinetRequest(cabinet=2))
    assert c["done"] == 0 and c["failed"][0]["motor_key"] == "gw2.1"
    await S._stop_pollers()
    print("ok")

asyncio.run(main())
