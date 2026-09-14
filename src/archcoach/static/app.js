document.addEventListener("DOMContentLoaded", () => {
  const token = document.querySelector('meta[name="archcoach-token"]')?.content || "";
  document.querySelectorAll("[data-dialog]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.dialog)?.showModal()));
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => button.closest("dialog")?.close()));
  document.querySelectorAll(".copy-task").forEach(button => button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.task); toast("Codex task copied");
  }));
  document.querySelectorAll(".lesson-status").forEach(select => select.addEventListener("change", async () => {
    const response = await fetch(`/reviews/${select.dataset.review}/lessons/${select.dataset.lesson}?token=${encodeURIComponent(token)}`, {method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token}, body:JSON.stringify({status:select.value})});
    toast(response.ok ? "Lesson progress saved" : "Could not save progress");
  }));
  document.querySelectorAll("[data-question]").forEach(button => button.addEventListener("click", () => {
    const area = document.querySelector('.chat-form textarea'); if (area) { area.value = button.dataset.question; area.focus(); }
  }));
  if (!window.htmx) {
    const poll = async () => {
      const state = document.getElementById("job-state");
      if (!state || !state.hasAttribute("hx-get")) return;
      const response = await fetch(state.getAttribute("hx-get"), {headers:{"HX-Request":"true"}});
      if (response.ok) state.outerHTML = await response.text();
    };
    setInterval(poll, 1200);
  }
  function toast(message) { const node = document.getElementById("toast"); node.textContent=message; node.classList.add("show"); setTimeout(()=>node.classList.remove("show"),1800); }
});

