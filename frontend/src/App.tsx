import { Link, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import "./App.css";
import { Lookup } from "./pages/Lookup";
import { MyForms } from "./pages/MyForms";
import { Questionnaire } from "./pages/Questionnaire";
import { ResponseDetail } from "./pages/ResponseDetail";

function Nav() {
  return (
    <nav className="topnav">
      <Link to="/">我的表單</Link>
      <Link to="/lookup">設計師查詢</Link>
    </nav>
  );
}

export default function App() {
  return (
    <Router>
      <Nav />
      <Routes>
        <Route path="/" element={<MyForms />} />
        <Route path="/edit/:id" element={<Questionnaire />} />
        <Route path="/lookup" element={<Lookup />} />
        <Route path="/lookup/:id" element={<ResponseDetail />} />
      </Routes>
    </Router>
  );
}
