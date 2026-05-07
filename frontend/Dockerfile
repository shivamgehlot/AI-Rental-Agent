FROM node:20-alpine

WORKDIR /app

COPY package.json /app/package.json
RUN npm install

COPY . /app

EXPOSE 3000

CMD ["sh", "-c", "npm run dev -- --host 0.0.0.0 --port 3000 || npm run start -- --host 0.0.0.0 --port 3000 || npx serve -s . -l 3000"]
