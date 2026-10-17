import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Dashboard } from "./pages/Dashboard";
import { Activity, Favorites, Recent } from "./pages/Collections";
import { Files } from "./pages/Files";
import { Login } from "./pages/Login";
import { Photos } from "./pages/Photos";
import { Register } from "./pages/Register";
import { Invites } from "./pages/Invites";
import { Security } from "./pages/Security";
import { Shares } from "./pages/Shares";
import { Trash } from "./pages/Trash";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/files" element={<Files />} />
          <Route path="/photos" element={<Photos />} />
          <Route path="/favorites" element={<Favorites />} />
          <Route path="/recent" element={<Recent />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/shares" element={<Shares />} />
          <Route path="/invites" element={<Invites />} />
          <Route path="/security" element={<Security />} />
          <Route path="/trash" element={<Trash />} />
        </Route>
      </Route>
    </Routes>
  );
}
