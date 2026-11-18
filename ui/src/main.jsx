// 芥子前端進入點（Phase 8 唯讀雛形）。 / Entry point of the Jiezi front end (Phase 8 read-only prototype).
import { Component } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./style.css";

// 畫面出錯時顯示原因，不再整片空白（使用者 2026-11-18：送出後畫面變空白）。
// Show what went wrong instead of a blank page (user report: the page went blank after sending).
class Crash extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    const e = this.state.error;
    if (!e) return this.props.children;
    return (
      <div className="card crash">
        <h2>畫面出錯了</h2>
        <p>請把下面的訊息複製給開發者。重新載入就能繼續使用，對話紀錄可能要重問。</p>
        <pre>{`${e.name || "Error"}: ${e.message || e}\n${(e.stack || "").split("\n").slice(0, 8).join("\n")}\n${navigator.userAgent}`}</pre>
        <button onClick={() => location.reload()}>重新載入</button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")).render(<Crash><App /></Crash>);
