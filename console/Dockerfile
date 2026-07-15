# Образ консоли Оператора (Ф4) для облака (Railway, #45 з.2): собранный SPA за nginx +
# прокси /api → ядро. Сборка в облаке (Railway builders / CI), НЕ локально (#12).
# Консоль — только дисплей; деньги-логика и авторизация живут в ядре (закон №3, #45).

# --- сборка статики ---
FROM node:20-slim AS build
WORKDIR /app
# Манифест первым — слой npm-зависимостей кэшируется при правках кода.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build            # tsc && vite build → /app/dist

# --- раздача за nginx ---
FROM nginx:1.27-alpine
# Наш конфиг заменяет дефолтный server{} (SPA-фолбэк + прокси /api → ядро).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# CMD наследуется из базового образа nginx (nginx -g 'daemon off;').
