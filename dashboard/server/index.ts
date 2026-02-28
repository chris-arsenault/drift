import path from "node:path";
import express from "express";
import { projectsRouter } from "./routes/projects.js";
import { libraryRouter } from "./routes/library.js";

const app = express();
const port = parseInt(process.env.DRIFT_UI_PORT ?? "47017", 10);

app.use(express.json());

app.use("/api/projects", projectsRouter);
app.use("/api/library", libraryRouter);

if (process.env.NODE_ENV === "production") {
  const distDir = path.join(import.meta.dirname, "..", "dist");
  app.use(express.static(distDir));
  app.get("/{*splat}", (_req, res) => {
    res.sendFile(path.join(distDir, "index.html"));
  });
}

app.listen(port, () => {
  console.log(`drift dashboard server listening on http://localhost:${port}`);
});
