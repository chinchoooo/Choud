import { Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "./components/ProtectedRoute";
import { Dashboard } from "./pages/Dashboard";
import { Files } from "./pages/Files";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Trash } from "./pages/Trash";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/files" element={<Files />} />
        <Route path="/trash" element={<Trash />} />
      </Route>
    </Routes>
  );
}
