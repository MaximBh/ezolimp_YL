document.documentElement.classList.add('dark');

const style = document.createElement('style');
style.textContent = `
  .dark body { background: #0f172a; color: #e2e8f0; }
  .dark nav { background: #1e293b !important; }
  .dark .bg-white { background: #1e293b !important; }
  .dark .bg-gray-50 { background: #0f172a !important; }
  .dark .text-gray-dark { color: #cbd5e1 !important; }
  .dark .text-gray-medium { color: #94a3b8 !important; }
  .dark .text-primary { color: #60a5fa !important; }
  .dark .border-gray-200 { border-color: #334155 !important; }
  .dark .border-gray-300 { border-color: #475569 !important; }
  .dark input, .dark select, .dark textarea { background: #334155 !important; color: #e2e8f0 !important; border-color: #475569 !important; }
  .dark .shadow-lg { box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important; }
  .dark .shadow-md { box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3) !important; }
  .dark footer { background: #0f172a !important; }
  .dark .bg-blue-50 { background: #1e3a5f !important; }
  .dark .bg-green-50 { background: #1e3a2f !important; }
  .dark .bg-purple-50 { background: #2e1e3a !important; }
  .dark .bg-red-50 { background: #3a1e1e !important; }
  .dark .bg-yellow-50 { background: #3a351e !important; }
  .dark .bg-gray-100 { background: #334155 !important; }
  .dark .bg-gray-200 { background: #475569 !important; }
  .dark .hover\:bg-gray-50:hover { background: #334155 !important; }
  .dark .hover\:bg-gray-300:hover { background: #64748b !important; }
`;
document.head.appendChild(style);
