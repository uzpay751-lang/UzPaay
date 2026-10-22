// Подключи в index.html ПОСЛЕ скрипта Telegram:
//   <script src="https://telegram.org/js/telegram-web-app.js"></script>
//   <script src="api.js"></script>

// Замени YOUR_PROJECT_REF на идентификатор проекта (часть Project URL до .supabase.co)
const API_URL = "https://YOUR_PROJECT_REF.supabase.co/functions/v1/api";

const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

async function api(action, payload = {}) {
  const res = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, initData: tg.initData, ...payload }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "request_failed");
  return data;
}

// Примеры использования:
//
// const { user } = await api("init");              // регистрация + баланс
// console.log(user.balance);
//
// const r = await api("create_order", { product_type: "example_product" });
// console.log(r.balance);                          // новый баланс
//
// const { orders } = await api("orders");          // история заказов
//
// Ошибки: "insufficient_funds" (мало денег), "unknown_product", "unauthorized".
