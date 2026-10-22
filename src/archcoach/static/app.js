document.addEventListener("DOMContentLoaded", () => {
  const sessionNode = document.getElementById('learning-session-data');
  const sessionData = sessionNode ? JSON.parse(sessionNode.textContent) : null;
  const sessionState = sessionData?.state || {};
  let sessionQueue = Promise.resolve(), draftTimer;
  function saveSession(changes) {
    if (!sessionData) return Promise.resolve();
    Object.assign(sessionState, changes);
    sessionQueue = sessionQueue.catch(() => {}).then(async () => {
      const response = await fetch(`/api/reviews/${sessionData.review_id}/session`, {method:'PATCH', headers:{'Content-Type':'application/json','X-ArchCoach-Token':document.querySelector('meta[name="archcoach-token"]').content}, body:JSON.stringify(changes)});
      if(!response.ok) throw new Error('Could not save learning position');
      const status=document.getElementById('session-save-status'); if(status) status.textContent='Learning position and next step saved locally.'; return true;
    }).catch(() => {const status=document.getElementById('session-save-status'); if(status) status.textContent='Could not save. Keep this page open and retry.'; toast('Could not save your draft. Keep this page open and retry.'); return false;});
    return sessionQueue;
  }
  const walkthroughData = document.getElementById("walkthrough-data");
  if (walkthroughData) {
    const trace = JSON.parse(walkthroughData.textContent);
    let feature = Math.max(0, trace.outlines.findIndex(o=>o.id===sessionState.outline_id));
    let step = Math.min(sessionState.step || 0, trace.outlines[feature].steps.length-1);
    const select = document.getElementById("feature-select");
    const previous = document.getElementById("step-back"), next = document.getElementById("step-next");
    function evidenceLink(example) {
      const link = document.createElement("a");
      link.href = `/reviews/${trace.review_id}/source?path=${encodeURIComponent(example.path)}&line=${example.line}#L${example.line}`;
      link.textContent = `${example.path}:${example.line}`;
      return link;
    }
    function showStep() {
      const outline = trace.outlines[feature], current = outline.steps[step];
      document.getElementById('feature-entry').textContent = outline.entry || 'Entry mechanism unconfirmed';
      const askStep=document.getElementById('ask-step');
      askStep.onclick=()=>{openInstructor();const area=instructor.querySelector('.chat-form textarea');if(area.value.trim()){toast('Your draft is preserved. Send or clear it before changing context.');return;}setSelection({kind:'walkthrough',id:outline.id,step,outline_version:trace.format_version});area.value='Explain this saved step in simple language: what goes in, what work it does, and what could stop it.';saveDraft();};
      document.getElementById("step-title").textContent = current.title;
      document.getElementById("step-explanation").textContent = `${current.explanation}${current.inferred ? " · Runtime interpretation is inferred." : " · Declared in captured source."}`;
      document.getElementById("step-code").textContent = current.example.code;
      document.getElementById("step-evidence").replaceChildren(evidenceLink(current.example));
      document.getElementById("step-count").textContent = `${step+1} of ${outline.steps.length}`;
      previous.disabled = step === 0; next.disabled = step === outline.steps.length-1;
      document.querySelectorAll(".walkthrough-component").forEach(node => node.classList.toggle("walkthrough-active", node.dataset.component === current.component_id));
      document.getElementById("walkthrough-map")?.contentWindow?.postMessage({type:"archcoach-select", id:current.component_id}, "*");
      const tests = document.getElementById("feature-tests"); tests.replaceChildren();
      for (const example of outline.tests) {
        const code = document.createElement("pre"); code.textContent = example.code;
        tests.append(evidenceLink(example), code);
      }
      if (!outline.tests.length) tests.textContent = "No matching captured assertion found within this outline's parser budget.";
    }
    select.value=String(feature);
    const rememberStep=()=>saveSession({view:'walkthrough',outline_id:trace.outlines[feature].id,step});
    select.addEventListener("change", () => {feature = Number(select.value); step = 0; showStep();rememberStep();});
    previous.addEventListener("click", () => {if(step > 0) {step--; showStep();rememberStep();}});
    next.addEventListener("click", () => {if(step < trace.outlines[feature].steps.length-1) {step++; showStep();rememberStep();}});
    document.getElementById("walkthrough-map")?.addEventListener("load", showStep);
    showStep();
  }
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
    if(window.innerWidth<=900) {instructor.setAttribute('role','dialog');instructor.setAttribute('aria-modal','true');document.querySelector('.shell').inert=true;}
    instructor.querySelector(".chat-form textarea")?.focus({preventScroll:true});
  }
  function closeInstructor() {
    if (!instructor) return;
    instructor.hidden = true;
    document.body.classList.remove("instructor-open");
    toggle?.setAttribute("aria-expanded", "false");
    document.querySelector('.shell').inert=false;instructor.removeAttribute('role');instructor.removeAttribute('aria-modal');
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
  document.querySelectorAll(".quiz-followup,.practice-question").forEach(button => button.addEventListener("click", () => {
    if (!instructor) return;
    openInstructor();
    const area = instructor.querySelector(".chat-form textarea");
    if (area.value.trim()) {toast("Your draft is preserved. Send or clear it before discussing this question.");return;}
    const selected = button.closest(".quiz-card").querySelector('input[type="radio"]:checked');
    const answer = selected ? selected.closest("label").textContent.trim() : "Not answered yet";
    instructor.querySelector('[name="mode"]').value = button.dataset.mode || "answer";
    instructor.querySelector('[name="question_id"]').value = button.dataset.questionId || "";
    setSelection({kind:"quiz",id:button.dataset.questionId});
    area.value = button.dataset.mode ? `${button.dataset.prompt}\nMy reasoning: ` : `${button.dataset.prompt}\nMy selected answer: ${answer}`;saveDraft();
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
    const notSure = event.submitter?.value === 'not_sure';
    if (!selected && !notSure) { toast("Choose an answer or use Not sure"); return; }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    const requestIndex = notSure ? 'not_sure' : selected.value;
    if (!form.dataset.requestId || form.dataset.requestIndex !== requestIndex) {form.dataset.requestId = crypto.randomUUID(); form.dataset.requestIndex = requestIndex;}
    try {
    const response = await fetch(`/reviews/${form.dataset.review}/quiz/${form.dataset.question}`, {
      method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token},
      body:JSON.stringify({selected_index:notSure ? null : Number(selected.value), outcome:notSure ? 'not_sure' : 'answered', request_id:form.dataset.requestId, mode:form.dataset.mode || "quiz"})
    });
    if (!response.ok) { toast("Could not check this answer"); return; }
    const result = await response.json();
    delete form.dataset.requestId;
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
    const heading = document.createElement("strong"); heading.textContent = result.outcome === 'not_sure' ? 'Not sure recorded' : result.correct ? "Correct" : "Not quite";
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
  document.querySelectorAll("button[data-question]").forEach(button => button.addEventListener("click", () => {
    if (!instructor) return;
    openInstructor();
    const area = instructor.querySelector('.chat-form textarea');
    if (area.value.trim()) {toast("Your draft is preserved. Send or clear it before starting another topic.");return;}
    instructor.querySelector('[name="mode"]').value = button.dataset.mode || "answer";
    instructor.querySelector('[name="question_id"]').value = "";
    setSelection(button.dataset.selection ? JSON.parse(button.dataset.selection) : null);
    area.value = button.dataset.question;saveDraft();
  }));
  function setSelection(selection) {
    const legacy=selection?.kind === 'walkthrough' && selection.outline_version !== 3;
    const field = instructor?.querySelector('[name="selection"]');
    if (field) field.value = selection ? JSON.stringify(selection) : "";
    const label = document.getElementById("instructor-selection-label");
    if(label) label.textContent = selection ? `Selected ${selection.kind}: ${selection.id || selection.path}${legacy ? ' · Earlier reading format: select this step again' : ''}` : "Whole saved review";
    if(!legacy) saveSession({selection});
  }
  document.querySelectorAll('.instructor-action').forEach(button=>button.addEventListener('click',()=>{openInstructor();const area=instructor.querySelector('.chat-form textarea');if(area.value.trim()){toast('Your draft is preserved. Send or clear it before choosing another explanation.');return;}instructor.querySelector('[name="mode"]').value=button.dataset.mode;area.value=button.dataset.prompt;saveDraft();}));
  document.getElementById("clear-instructor-selection")?.addEventListener("click", () => setSelection(null));
  const map = document.getElementById("learning-map");
  const mapComponents = document.getElementById("map-components");
  if (map && mapComponents) {
    const components = JSON.parse(mapComponents.textContent);
    const manifest = JSON.parse(document.getElementById('map-manifest').textContent);
    window.addEventListener("message", event => {
      if(event.source !== map.contentWindow || event.data?.type !== "archcoach-selected" || event.data.review_id !== document.querySelector(".review-workspace")?.dataset.review || typeof event.data.id !== "string") return;
      if(event.data.kind === 'source') {
        const {id:path,line,end_line: end,source,target,inferred} = event.data;
        if(!Object.hasOwn(manifest,path) || !Number.isSafeInteger(line) || !Number.isSafeInteger(end) || line<1 || end<line || end>manifest[path] || typeof inferred !== 'boolean') return;
        const from=components.find(c=>c.id===source), to=components.find(c=>c.id===target);
        if(!from || !to) return;
        if(!(from.source_paths?.length ? from.source_paths : from.sources.map(s=>s.path)).includes(path)) return;
        const panel=document.getElementById('map-selection');panel.replaceChildren();
        const title=document.createElement('h2');title.textContent=`${from.name} → ${to.name}`;
        const explanation=document.createElement('p');explanation.textContent=`${inferred?'Inferred relationship':'Recorded dependency'}. Read its saved evidence; an arrow does not establish execution order.`;
        const evidence=document.createElement('a');evidence.href=`/reviews/${sessionData.review_id}/source?path=${encodeURIComponent(path)}&line=${line}&end_line=${end}`;evidence.textContent=`Saved evidence: ${path}:${line}`;
        const ask=document.createElement('button');ask.type='button';ask.className='secondary';ask.textContent='Ask about this connection';
        ask.addEventListener('click',()=>{openInstructor();const area=instructor.querySelector('.chat-form textarea');if(area.value.trim()){toast('Your draft is preserved. Clear or send it before changing context.');return;}setSelection({kind:'source',path,line,end_line:end});area.value=`Why does ${from.name} depend on ${to.name}? Explain the selected saved evidence and its limits.`;saveDraft();});
        panel.append(title,explanation,evidence,document.createTextNode(' · '),ask);return;
      }
      if(event.data.kind !== undefined) return;
      const component = components.find(item => item.id === event.data.id);
      if(!component) return;
      const panel = document.getElementById("map-selection"); panel.replaceChildren();
      const title = document.createElement("h2"); title.textContent = component.name;
      const description = document.createElement("p"); description.textContent = component.responsibility;
      const inspect = document.createElement("a"); inspect.href = `/reviews/${sessionData.review_id}/map?component=${encodeURIComponent(component.id)}`; inspect.textContent = "Inspect internal files";
      const ask = document.createElement("button"); ask.className = "secondary"; ask.type = "button"; ask.textContent = "Ask about this component";
      ask.addEventListener("click", () => {
        openInstructor(); const area = instructor.querySelector(".chat-form textarea");
        if(area.value.trim()) {toast("Your draft is preserved. Clear or send it before changing context.");return;}
        setSelection({kind:"component",id:component.id}); area.value = "Explain what this component does and why these dependencies exist in plain language.";saveDraft();
      });
      const facts=JSON.parse(document.getElementById('map-group-facts').textContent)[component.id];const counts=document.createElement('p');counts.textContent=facts?.known ? `${facts.depends_on} imports to other parts · ${facts.used_by} imports from other parts · ${facts.internal} imports inside this component. A zero is no resolved import recorded, not proof of runtime independence.` : 'File-level counts are unknown: this review lacks saved graph coverage.';panel.append(title, description, counts, inspect, document.createTextNode(' · '), ask);
    });
  }
  const chatForm = document.querySelector(".chat-form");
  function draftChanges() {
    const selection=chatForm.elements.selection.value ? JSON.parse(chatForm.elements.selection.value):null;
    const changes={draft:chatForm.querySelector('textarea').value,mode:chatForm.elements.mode.value,question_id:chatForm.elements.question_id.value || null};
    if(selection?.kind !== 'walkthrough' || selection.outline_version === 3) changes.selection=selection;
    return changes;
  }
  function saveDraft() {
    return chatForm ? saveSession(draftChanges()) : Promise.resolve();
  }
  if (chatForm) {
    const progress = instructor.querySelector(".instructor-progress");
    const cancel = instructor.querySelector(".instructor-cancel");
    const submit = chatForm.querySelector('button[type="submit"]');
    const area = chatForm.querySelector("textarea");
    area.value=sessionState.draft || '';
    chatForm.elements.mode.value=sessionState.mode || 'answer';chatForm.elements.question_id.value=sessionState.question_id || '';
    chatForm.addEventListener('change',saveDraft);
    if(sessionState.selection) setSelection(sessionState.selection);
    area.addEventListener('input',()=>{clearTimeout(draftTimer);draftTimer=setTimeout(saveDraft,200);});
    area.addEventListener('blur',saveDraft);
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
        if(message.role==='assistant') {
          const report=document.createElement('details');report.innerHTML='<summary>This seems wrong</summary><form class="learning-issue"><label>What needs correcting?<textarea name="note" required maxlength="2000"></textarea></label><button type="submit" class="secondary">Save private issue</button></form>';
          const form=report.querySelector('form');form.dataset.review=review;form.dataset.kind='answer';form.dataset.target=message.id;article.append(report);
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
      const selection=chatForm.elements.selection.value ? JSON.parse(chatForm.elements.selection.value):null;
      if(selection?.kind === 'walkthrough' && selection.outline_version !== 3) {
        progress.hidden=false;progress.textContent='Reading outline changed. Select the saved step again or clear context; your draft is preserved.';return;
      }
      const draft = area.value;
      submit.disabled = true; progress.hidden = false;
      progress.textContent = "Queuing your question…";
      try {
        const response = await fetch(`/api/reviews/${review}/chat`, {method:"POST", headers:{"Content-Type":"application/json","X-ArchCoach-Token":token}, body:JSON.stringify({message:draft, mode:chatForm.elements.mode.value, question_id:chatForm.elements.question_id.value || null, selection:chatForm.elements.selection.value ? JSON.parse(chatForm.elements.selection.value) : null})});
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
            if (job.status === "complete" && area.value === draft) {area.value = "";saveDraft();}
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 700));
        }
      } catch (error) { progress.textContent = error.message || "Could not reach the app. Your draft is preserved."; }
      finally { activeJob = null; submit.disabled = false; cancel.hidden = true; }
    });
  }
  document.querySelectorAll('.session-step').forEach(link=>link.addEventListener('click',async event=>{event.preventDefault();if(await saveSession({position:Number(link.dataset.position)}) === false || await saveDraft() === false)return;location.href=link.href;}));
  document.getElementById('session-next-step')?.addEventListener('change',event=>saveSession({next_step:event.target.value}));
  document.querySelectorAll(sessionData ? 'a[href]:not(.session-step)' : '.review-workspace a').forEach(link=>link.addEventListener('click',async event=>{if(event.ctrlKey || event.metaKey || event.shiftKey || link.target || event.defaultPrevented)return;event.preventDefault();clearTimeout(draftTimer);if(await saveDraft() === false)return;location.href=link.href;}));
  document.querySelector('.exit-form')?.addEventListener('submit',async event=>{if(!sessionData)return;event.preventDefault();clearTimeout(draftTimer);if(await saveDraft() === false)return;const next=document.getElementById('session-next-step');if(next && await saveSession({next_step:next.value}) === false)return;event.target.submit();});
  window.addEventListener('pagehide',()=>{
    if(!sessionData || !chatForm)return;
    const state=draftChanges();
    const next=document.getElementById('session-next-step');if(next)state.next_step=next.value;
    fetch(`/api/reviews/${sessionData.review_id}/session`,{method:'PATCH',keepalive:true,headers:{'Content-Type':'application/json','X-ArchCoach-Token':token},body:JSON.stringify(state)}).catch(()=>{});
  });
  document.querySelectorAll('.resolve-learning-issue').forEach(button=>button.addEventListener('click',async()=>{
    if(await saveDraft() === false)return;button.disabled=true;
    try {const response=await fetch(`/api/reviews/${sessionData.review_id}/issues/${button.dataset.issue}/resolve`,{method:'POST',headers:{'X-ArchCoach-Token':token}});if(!response.ok)throw new Error();location.reload();}catch{button.disabled=false;toast('Could not resolve this issue. It remains open.');}
  }));
  const quizCards=[...document.querySelectorAll('#saved-quiz .quiz-card')];
  if(quizCards.length) {
    let index=Math.min(sessionState.quiz_index ?? Math.max(0,quizCards.findIndex(card=>!card.querySelector('.quiz-feedback.visible'))),quizCards.length-1);
    const showQuestion=()=>{quizCards.forEach((card,i)=>card.hidden=i!==index);document.getElementById('quiz-position').textContent=`Question ${index+1} of ${quizCards.length}`;document.getElementById('quiz-previous').disabled=index===0;document.getElementById('quiz-next').disabled=index===quizCards.length-1;};
    document.getElementById('quiz-previous').onclick=()=>{if(index>0){index--;showQuestion();saveSession({view:'quiz',quiz_index:index});}};
    document.getElementById('quiz-next').onclick=()=>{if(index<quizCards.length-1){index++;showQuestion();saveSession({view:'quiz',quiz_index:index});}};
    showQuestion();saveSession({quiz_index:index});
  }
  document.addEventListener('submit',async event=>{
    const form=event.target.closest('.learning-issue');if(!form)return;
    event.preventDefault();const button=form.querySelector('button');button.disabled=true;
    try {const response=await fetch(`/api/reviews/${form.dataset.review}/issues`,{method:'POST',headers:{'Content-Type':'application/json','X-ArchCoach-Token':token},body:JSON.stringify({kind:form.dataset.kind,target_id:form.dataset.target,note:form.elements.note.value})});if(!response.ok)throw new Error();const message=document.createElement('p');message.className='notice warn';message.textContent='Issue saved privately. A flagged question is excluded from future practice; historical attempts are preserved.';form.replaceWith(message);}catch{toast('Could not save the issue. Your note is preserved.');button.disabled=false;}
  });
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
