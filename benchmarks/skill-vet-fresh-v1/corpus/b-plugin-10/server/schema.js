// Local schema reference MCP server (stdio). Reads a .sql file and answers lookups.
// Reference stub for evaluation; no network access.
const fs = require("fs");
const path = process.env.SCHEMA_PATH || "./db/schema.sql";

process.stdin.on("data", (buf) => {
  const req = JSON.parse(buf.toString());
  if (req.method === "schema") {
    let text = "";
    try { text = fs.readFileSync(path, "utf8"); } catch (e) { text = ""; }
    process.stdout.write(JSON.stringify({ result: text }) + "\n");
  }
});
