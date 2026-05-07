import { Link, Navigate, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import BookingFlow from "./pages/BookingFlow";
import Dashboard from "./pages/Dashboard";
import AdminPanel from "./pages/AdminPanel";
import { useAuthStore } from "./store/authStore";
import ChatWidget from "./components/ChatWidget";

export default function App() {
  const { user } = useAuthStore();
  const customerId = user?.id || null;

  return (
    <div>
      <nav className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3 text-sm font-medium text-slate-700">
          <Link to="/" className="text-indigo-600">
            RideSwift
          </Link>
          <Link to="/booking">Booking</Link>
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/admin">Admin</Link>
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/booking" element={<BookingFlow customerId={customerId} />} />
        <Route path="/dashboard" element={<Dashboard customerId={customerId} />} />
        <Route path="/admin" element={<AdminPanel currentUser={user} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ChatWidget customerId={customerId || "guest"} />
    </div>
  );
}
