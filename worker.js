export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 上传接口
    if (url.pathname === "/upload" && request.method === "POST") {
      const filename = url.searchParams.get("name");
      if (!filename) {
        return new Response("missing name", { status: 400 });
      }

      const data = await request.text();  // KV 只存字符串
      await env.M3U_KV.put(filename, data);

      return Response.json({
        success: true,
        filename,
        url: `${url.origin}/f/${encodeURIComponent(filename)}`
      });
    }

    // 下载接口
    if (url.pathname.startsWith("/f/")) {
      const filename = decodeURIComponent(url.pathname.substring(3));
      const data = await env.M3U_KV.get(filename);
      if (!data) return new Response("Not Found", { status: 404 });

      return new Response(data, {
        headers: {
          "Content-Disposition": `attachment; filename="${filename}"`,
          "Content-Type": "application/octet-stream"
        }
      });
    }

    return new Response("OK");
  }
};
