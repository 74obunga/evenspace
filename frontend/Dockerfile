FROM node:24-alpine
WORKDIR /app
ARG VITE_API_BASE_URL=https://evenspace-api.onrender.com/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
