document.addEventListener("DOMContentLoaded", () => {
  const token = document.querySelector('meta[name="archcoach-token"]')?.content || "";
  const instructor = document.getElementById("chat");
  const toggle = document.querySelector(".instructor-toggle");
  let returnFocus = null;
  function openInstructor() {
    if (!instructor) return;
    returnFocus = document.activeElement;
    instructor.hidden = false;
    document.body.classList.add("instructor-open");
    toggle?.setAttribute("aria-expanded", "true");
    instructor.querySelector("textarea")?.focus({preventScroll:true});
  }
  function closeInstructor() {
    if (!instructor) return;
    instructor.hidden = true;
    document.body.classList.remove("instructor-open");
    toggle?.setAttribute("aria-expanded", "false");
    returnFocus?.focus({preventScroll:true});
  }
  toggle?.addEventListener("click", () => instructor.hidden ? openInstructor() : closeInstructor());
  document.querySelector(".instructor-close")?.addEventListener("click", closeInstructor);
  document.querySelector('a[href="#chat"]')?.addEventListener("click", event => {event.preventDefault();openInstructor();});
  if (location.hash === "#chat") openInstructor();
  window.addEventListener("hashchange", () => {if(location.hash === "#chat") openInstructor();});
  instructor?.addEventListener("keydown", event => {
    if(event.key === "Escape") {event.preventDefault();closeInstructor();}
    if(event.key === "Tab" && window.innerWidth <= 900) {
      const nodes = [...instructor.querySelectorAll('button,textarea,a,input,select')].filter(node => !node.disabled && node.getClientRects().length);
      if(event.shiftKey && document.activeElement === nodes[0]) {event.preventDefault();nodes.at(-1)?.focus();}
      else if(!event.shiftKey && document.activeElement === nodes.at(-1)) {event.preventDefault();nodes[0]?.focus();}
    }
  });
  document.querySelectorAll(".quiz-followup").forEach(button => button.addEventListener("click", () => {
    openInstructor();
    const area = instructor.querySelector("textarea");
    if (area.value.trim()) {toast("Your draft is preserved. Send or clear it before discussing this question.");return;}
    const selected = button.closest(".quiz-card").querySelector('input[type="radio"]:checked');
    const answer = selected ? selected.closest("label").textContent.trim() : "Not answered yet";
    area.value = `${button.dataset.prompt}\nMy selected answer: ${answer}`;
  }));
  document.querySelectorAll("[data-dialog]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.dialog)?.showModal()));
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => button.closest("dialog")?.close()));
  document.querySelectorAll(".copy-task").forEach(button => button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.task); toast("Codex task copied");
  }));
  document.querySelectorAll(".lesson-status").forEach(select => select.addEventListener("change", async () => {
    const response = await fetch(`/reviews/${select.dataset.review}/lessons/${select.dataset.lesson}`, {method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token}, body:JSON.stringify({status:select.value})});
    toast(response.ok ? "Lesson progress saved" : "Could not save progress");
  }));
  document.querySelectorAll(".quiz-form").forEach(form => form.addEventListener("submit", async event => {
    event.preventDefault();
    const selected = form.querySelector('input[type="radio"]:checked');
    if (!selected) { toast("Choose an answer first"); return; }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
    const response = await fetch(`/reviews/${form.dataset.review}/quiz/${form.dataset.question}`, {
      method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token},
      body:JSON.stringify({selected_index:Number(selected.value)})
    });
    if (!response.ok) { toast("Could not check this answer"); return; }
    const result = await response.json();
    const card = form.closest(".quiz-card");
    card.querySelectorAll(".quiz-option").forEach(option => {
      const index = Number(option.dataset.index);
      option.classList.toggle("selected", index === result.selected_index);
      option.classList.toggle("correct", index === result.correct_index);
      option.classList.toggle("incorrect", index === result.selected_index && !result.correct);
    });
    const feedback = card.querySelector(".quiz-feedback");
    feedback.className = `quiz-feedback visible ${result.correct ? "correct" : "incorrect"}`;
    feedback.replaceChildren();
    const heading = document.createElement("strong"); heading.textContent = result.correct ? "Correct" : "Not quite";
    const explanation = document.createElement("p"); explanation.textContent = result.explanation;
    feedback.append(heading, explanation);
    if (!result.correct) { const answer = document.createElement("p"); const label = document.createElement("b"); label.textContent="Correct answer: "; answer.append(label, document.createTextNode(result.correct_answer)); feedback.append(answer); }
    const answered = document.getElementById("quiz-answered"), score = document.getElementById("quiz-score");
    if (answered) answered.textContent = document.querySelectorAll(".quiz-feedback.visible").length;
    if (score) score.textContent = document.querySelectorAll(".quiz-feedback.visible.correct").length;
    toast(result.correct ? "Correct answer" : "Answer explained");
    } catch (error) {
      toast("Could not reach the app. Your selected answer is preserved; try again.");
    } finally {
      submit.disabled = false;
    }
  }));
  const currentStatus = document.getElementById("current-file-status");
  if (currentStatus) fetch(`/api/reviews/${currentStatus.dataset.review}/current-status`).then(async response => {
    if (!response.ok) throw new Error("status check failed");
    const result = await response.json();
    const labels = {matches:"Matches current files", changed:"Files changed since this review", folder_unavailable:"Source folder unavailable"};
    currentStatus.textContent = labels[result.status] || "Current-file status unavailable";
    currentStatus.className = `pill ${result.status === "matches" ? "ok" : "warn"}`;
  }).catch(() => { currentStatus.textContent = "Current-file status unavailable"; currentStatus.className = "pill warn"; });
  document.querySelectorAll(".suggestions button[data-question]").forEach(button => button.addEventListener("click", () => {
    const area = document.querySelector('.chat-form textarea'); if (area) { area.value = button.dataset.question; area.focus(); }
  }));
  const chatForm = document.querySelector(".chat-form");
  if (chatForm) {
    const progress = instructor.querySelector(".instructor-progress");
    const cancel = instructor.querySelector(".instructor-cancel");
    const submit = chatForm.querySelector('button[type="submit"]');
    const area = chatForm.querySelector("textarea");
    const review = chatForm.dataset.review;
    let activeJob = null;
    async function refreshConversation() {
      const response = await fetch(`/api/reviews/${review}/conversation`);
      if (!response.ok) throw new Error("Could not load saved answers.");
      const conversation = await response.json();
      const log = instructor.querySelector(".chat-log");
      log.replaceChildren();
      for (const message of conversation.messages) {
        const article = document.createElement("article");
        article.className = `message ${message.role === "user" ? "user" : "assistant"}`;
        const label = document.createElement("span");
        label.textContent = `${message.role === "user" ? "You" : "Coach"}${message.status === "failed" ? " · failed" : ""}`;
        const content = document.createElement("p"); content.textContent = message.content;
        article.append(label, content);
        for (const citation of message.citations || []) {
          const link = document.createElement(citation.valid ? "a" : "span");
          link.className = "evidence";
          link.textContent = `${citation.path}:${citation.line}${citation.valid ? "" : " · unverified"}`;
          if (citation.valid) {
            link.href = `/reviews/${review}/source?path=${encodeURIComponent(citation.path)}&line=${citation.line}#L${citation.line}`;
            link.target = "_blank"; link.rel = "noopener";
          }
          article.append(link);
        }
        log.append(article);
      }
    }
    cancel.addEventListener("click", async () => {
      if (!activeJob) return;
      cancel.disabled = true;
      try {
        const response = await fetch(`/api/jobs/${activeJob}/cancel`, {method:"POST", headers:{"X-ArchCoach-Token":token}});
        if (!response.ok) throw new Error();
        progress.textContent = "Cancellation requested…";
      } catch { toast("Could not cancel. Try again."); }
      finally { cancel.disabled = false; }
    });
    chatForm.addEventListener("submit", async event => {
      event.preventDefault();
      if (activeJob || submit.disabled) return;
      const draft = area.value;
      submit.disabled = true; progress.hidden = false;
      progress.textContent = "Queuing your question…";
      try {
        const response = await fetch(`/api/reviews/${review}/chat`, {method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token}, body:JSON.stringify({message:draft})});
        if (!response.ok) throw new Error("Could not queue your question. Your draft is preserved.");
        activeJob = (await response.json()).job_id; cancel.hidden = false;
        for (;;) {
          const state = await fetch(`/api/jobs/${activeJob}`);
          if (!state.ok) throw new Error("Could not check the answer. Check job history before retrying.");
          const job = await state.json();
          progress.textContent = `${job.stage || job.status} · ${Math.round(job.elapsed_seconds || 0)}s${job.usage ? ` · ${job.usage.input_tokens ?? "?"} input / ${job.usage.output_tokens ?? "?"} output tokens` : ""}`;
          if (["complete", "failed", "cancelled"].includes(job.status)) {
            await refreshConversation();
            progress.textContent = job.status === "complete" ? "Answer saved with this review." : `${job.status}: ${job.error || "No completed answer was saved."}`;
            if (job.status === "complete" && area.value === draft) area.value = "";
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 700));
        }
      } catch (error) { progress.textContent = error.message || "Could not reach the app. Your draft is preserved."; }
      finally { activeJob = null; submit.disabled = false; cancel.hidden = true; }
    });
  }
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
