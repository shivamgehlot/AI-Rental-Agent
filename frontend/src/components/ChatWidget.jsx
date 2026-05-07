// frontend/src/components/ChatWidget.jsx
import { useState, useEffect, useRef } from "react";
import { io } from "socket.io-client";

export default function ChatWidget({ customerId }) {
  const [messages, setMessages] = useState([
    { from: "bot", text: "Hi! I'm your RideSwift assistant. How can I help you today?" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const socket = useRef(null);

  useEffect(() => {
    socket.current = io(process.env.REACT_APP_API_URL);
    socket.current.on("inventory_update", (data) => {
      setMessages(prev => [...prev, {
        from: "bot", text: `🚗 Update: ${data.message}`
      }]);
    });
    return () => socket.current.disconnect();
  }, []);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg = { from: "user", text: input };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const res = await fetch(`${process.env.REACT_APP_API_URL}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input, customer_id: customerId })
    });
    const data = await res.json();
    setMessages(prev => [...prev, { from: "bot", text: data.response }]);
    setLoading(false);
  };

  return (
    <div className="fixed bottom-4 right-4 w-80 bg-white rounded-2xl shadow-xl">
      <div className="bg-indigo-600 text-white p-3 rounded-t-2xl font-medium">
        RideSwift Assistant 🚗
      </div>
      <div className="h-72 overflow-y-auto p-3 space-y-2">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.from === "user" ? "justify-end" : "justify-start"}`}>
            <span className={`px-3 py-2 rounded-xl text-sm max-w-[85%] ${
              m.from === "user" ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-800"
            }`}>{m.text}</span>
          </div>
        ))}
        {loading && <div className="text-xs text-gray-400 italic">Thinking...</div>}
      </div>
      <div className="p-2 border-t flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Ask about rentals..."
          className="flex-1 border rounded-lg px-2 py-1 text-sm outline-none" />
        <button onClick={sendMessage}
          className="bg-indigo-600 text-white px-3 py-1 rounded-lg text-sm">
          Send
        </button>
      </div>
    </div>
  );
}