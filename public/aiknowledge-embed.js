(function (global) {
  "use strict";

  /**
   * Mount the public Q&A page in an existing site.
   *
   * Usage:
   *   AiKnowledgeEmbed.mount({ token: "...", target: "#knowledge-widget" });
   *
   * The token is never sent to this script's server. It is passed directly to
   * the public page, where the normal password, Origin allowlist and rate-limit
   * checks still apply.
   */
  function mount(options) {
    options = options || {};
    var token = typeof options.token === "string" ? options.token.trim() : "";
    if (!token) throw new Error("AiKnowledgeEmbed requires a share token.");
    var target = options.target;
    if (typeof target === "string") target = document.querySelector(target);
    if (!target || !(target instanceof HTMLElement)) {
      throw new Error("AiKnowledgeEmbed target was not found.");
    }
    var publicUrl = options.publicUrl || new URL("/public", global.location.href).toString();
    var url = new URL(publicUrl, global.location.href);
    url.searchParams.set("token", token);
    var iframe = document.createElement("iframe");
    iframe.src = url.toString();
    iframe.title = options.title || "知溯公开知识问答";
    iframe.loading = "lazy";
    iframe.referrerPolicy = "no-referrer";
    iframe.style.width = "100%";
    iframe.style.minHeight = (options.height || 680) + "px";
    iframe.style.border = "0";
    iframe.style.borderRadius = "14px";
    iframe.style.background = "#f8fbff";
    target.replaceChildren(iframe);
    return {
      iframe: iframe,
      destroy: function () {
        if (iframe.parentNode === target) target.removeChild(iframe);
      }
    };
  }

  global.AiKnowledgeEmbed = { mount: mount };
})(window);
