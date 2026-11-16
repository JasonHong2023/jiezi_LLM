"""桌面 App 雛形測試：頁面帶 CSP、管理接口要金鑰、稽核紀錄格式。 / Desktop prototype tests."""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


class TestUi(unittest.TestCase):
    def test_static_csp_and_admin(self):
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "ui" / "dist").mkdir(parents=True)
            (tmp / "ui" / "dist" / "index.html").write_text("<html>芥子</html>", encoding="utf-8")
            (tmp / "var" / "trajectories").mkdir(parents=True)
            rec = {"id": "t1", "at": "2026-11-16T10:00:00+08:00", "policy": "jiezi", "status": "ok", "final_tier": 0,
                   "training_use": None, "sources": [{"source": "moj-laws"}],
                   "request": {"messages": [{"role": "user", "content": "民法第184條"}]}}
            (tmp / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(json.dumps(rec, ensure_ascii=False))
            sup, _, patch = make_supervisor(tmp)
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.get("/ui/")
                self.assertEqual(r.status_code, 200)
                self.assertIn("default-src 'self'", r.headers["content-security-policy"])
                self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
                self.assertEqual(c.get("/admin/trajectories").status_code, 401)
                self.assertEqual(c.get("/admin/doctor").status_code, 401)
                h = {"Authorization": f"Bearer {KEY}"}
                t = c.get("/admin/trajectories?limit=5", headers=h).json()["records"]
                self.assertEqual((t[0]["question"], t[0]["sources"]), ("民法第184條", ["moj-laws"]))
                self.assertIn("checks", c.get("/admin/doctor", headers=h).json())

    def test_no_ui_without_build(self):
        from jiezi.runtime.gateway import ui_routes
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ui_routes(Path(d)), [])


if __name__ == "__main__":
    unittest.main()
