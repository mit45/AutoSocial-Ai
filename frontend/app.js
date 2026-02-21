(function () {
  "use strict";

  // Frontend ve API aynı uvicorn instance'ından servis ediliyor.
  // Bu yüzden her zaman aynı origin üzerinden /api kullanıyoruz.
  // Örn: http://127.0.0.1:9000/ -> http://127.0.0.1:9000/api
  const API_BASE = "/api";

  function getJson(url, options = {}) {
    return fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    }).then((r) => {
      if (!r.ok) {
        return r.text().then((text) => {
          let msg = r.statusText;
          try {
            const d = JSON.parse(text);
            if (d.detail) msg = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
          } catch (_) {
            if (text) msg = text.slice(0, 200);
          }
          return Promise.reject(new Error(msg));
        });
      }
      return r.json();
    });
  }

  function postJson(url, body) {
    return getJson(url, {
      method: "POST",
      body: JSON.stringify(body || {}),
    });
  }

  function deleteJson(url) {
    return fetch(url, { method: "DELETE" }).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (text) {
          var msg = r.statusText;
          try {
            var d = JSON.parse(text);
            if (d.detail) msg = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
          } catch (_) {
            if (text) msg = text.slice(0, 200);
          }
          return Promise.reject(new Error(msg));
        });
      }
      return r.status === 204 || r.headers.get("content-length") === "0" ? {} : r.json();
    });
  }

  function showMessage(el, text, type) {
    if (!el) return;
    el.textContent = text;
    el.className = "message " + (type === "error" ? "error" : "success");
    el.hidden = false;
  }

  function hideMessage(el) {
    if (!el) return;
    el.hidden = true;
  }

  function statusBadge(status) {
    const s = (status || "").toLowerCase();
    const map = {
      draft: "badge-draft",
      approved: "badge-approved",
      published: "badge-published",
      failed: "badge-failed",
    };
    const label = { draft: "Taslak", approved: "Onaylı", published: "Yayında", failed: "Hata" };
    const cls = map[s] || "badge-draft";
    const text = label[s] || status || "—";
    return `<span class="badge ${cls}">${text}</span>`;
  }

  function formatDate(iso) {
    if (!iso) return "—";
    // API UTC gönderiyor; Z yoksa UTC kabul et ki yerel saate çevrilsin
    var s = String(iso).trim();
    if (s && !/Z|[+-]\d{2}:?\d{2}$/.test(s)) s = s.replace(/\.\d+$/, "") + "Z";
    const d = new Date(s);
    return d.toLocaleDateString("tr-TR", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function imageUrl(url) {
    if (!url) return "";
    if (url.startsWith("http")) return url;
    return url.startsWith("/") ? url : "/" + url;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  // ——— Generate form ———
  const formGenerate = document.getElementById("form-generate");
  const btnGenerate = document.getElementById("btn-generate");
  const messageGenerate = document.getElementById("generate-message");

  // Auto-resize textarea for multi-line topic input
  function autosizeTextarea(el) {
    if (!el) return;
    el.style.height = "auto";
    const scrollHeight = el.scrollHeight;
    el.style.height = Math.max(scrollHeight, 48) + "px";
  }
  const topicTextarea = document.getElementById("topic");
  if (topicTextarea) {
    // initialize size
    autosizeTextarea(topicTextarea);
    topicTextarea.addEventListener("input", function () {
      autosizeTextarea(topicTextarea);
    });
  }

  if (formGenerate) {
    formGenerate.addEventListener("submit", function (e) {
      e.preventDefault();
      const topic = (document.getElementById("topic") || {}).value?.trim() || undefined;
      hideMessage(messageGenerate);
      btnGenerate.classList.add("loading");
      btnGenerate.disabled = true;

      postJson(API_BASE + "/generate", { topic: topic || null })
        .then(function (res) {
          showMessage(
            messageGenerate,
            "İçerik oluşturuldu. Gönderi taslak olarak kaydedildi (ID: " + res.post_id + ").",
            "success"
          );
          loadPosts(currentStatusFilter);
          // Reset topic textarea to initial empty state and resize
          if (typeof topicTextarea !== "undefined" && topicTextarea) {
            topicTextarea.value = "";
            // reset height to initial
            topicTextarea.style.height = "auto";
            autosizeTextarea(topicTextarea);
          } else if (document.getElementById("topic")) {
            const t = document.getElementById("topic");
            t.value = "";
            t.style.height = "auto";
          }
        })
        .catch(function (err) {
          showMessage(messageGenerate, err.message || "İçerik üretilirken hata oluştu.", "error");
        })
        .finally(function () {
          btnGenerate.classList.remove("loading");
          btnGenerate.disabled = false;
        });
    });
  }

  // ——— Posts list ———
  const postsCards = document.getElementById("posts-cards");
  const postsEmpty = document.getElementById("posts-empty");
  let currentStatusFilter = "";

  function toDatetimeLocalString(date) {
    var d = date instanceof Date ? date : new Date(date);
    return (
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0") +
      "T" +
      String(d.getHours()).padStart(2, "0") +
      ":" +
      String(d.getMinutes()).padStart(2, "0")
    );
  }
  function scheduleInputMinValue() {
    return toDatetimeLocalString(new Date());
  }

  function renderPostCard(post) {
    const imgSrc = imageUrl(post.image_url || "");
    const caption = (post.caption || "").slice(0, 120) + ((post.caption || "").length > 120 ? "…" : "");
    const statusBadgeHtml = statusBadge(post.status);
    // Yayındaysa yayınlama saatini, değilse oluşturma saatini göster (yerel saat)
    const dateStr = post.status === "published" && post.published_at
      ? formatDate(post.published_at)
      : formatDate(post.created_at);
    const scheduledStr = post.scheduled_at ? formatDate(post.scheduled_at) : null;
    const scheduleMin = scheduleInputMinValue();

    const actions = [];
    if (post.status === "draft") {
      actions.push(
        '<button type="button" class="btn btn-secondary btn-approve" data-id="' +
          post.id +
          '">Onayla</button>'
      );
    }
    // Show publish buttons for approved posts — and also for failed posts so user can retry publishing.
    if (post.status === "approved" || post.status === "failed") {
      actions.push(
        '<button type="button" class="btn btn-success btn-publish-post" data-id="' +
          post.id +
          '">Yayınla (Post)</button>',
        '<button type="button" class="btn btn-outline-success btn-publish-story" data-id="' +
          post.id +
          '">Yayınla (Story)</button>'
      );
    }
    // "Yeniden Yayınla" sadece yayınlandıysa göster. Her durumda Sil butonu göster.
    if (post.status === "published") {
      actions.push(
        '<button type="button" class="btn btn-success btn-republish" data-id="' +
          post.id +
          '">Yeniden Yayınla</button>'
      );
    }
    actions.push(
      '<button type="button" class="btn btn-danger btn-delete-post" data-id="' +
        post.id +
        '">Sil</button>'
    );
    actions.push(
      '<button type="button" class="btn btn-secondary btn-detail" data-id="' +
        post.id +
        '">Detay</button>'
    );

    return (
      '<article class="post-card" data-id="' +
      post.id +
      '" data-status="' +
      (post.status || "") +
      '">' +
      (imgSrc
        ? '<img class="post-card-thumb" src="' + escapeHtml(imgSrc) + '" alt="" loading="lazy" />'
        : '<div class="post-card-thumb"></div>') +
      '<div class="post-card-body">' +
      '<div class="post-card-meta">' +
      statusBadgeHtml +
      '<span class="post-card-date">' +
      escapeHtml(dateStr) +
      "</span>" +
      (scheduledStr
        ? '<span class="post-card-scheduled" style="color: var(--status-approved); font-size: 0.8125rem; margin-left: 0.5rem;">⏰ ' +
          escapeHtml(scheduledStr) +
          "</span>"
        : "") +
      "</div>" +
      '<p class="post-card-caption">' +
      escapeHtml(caption || "—") +
      "</p>" +
      '<div class="post-card-actions">' +
      actions.join("") +
      "</div>" +
      '<div class="post-card-schedule" style="margin-top: 0.5rem; display: flex; gap: 0.5rem; align-items: center; font-size: 0.8125rem;">' +
      // Schedule for POST
      '<label style="display: flex; align-items: center; gap: 0.25rem; color: var(--text-muted);">' +
      '<input type="checkbox" class="schedule-checkbox-post" data-id="' +
      post.id +
      '" ' +
      'style="margin: 0;" />' +
      "Zamanla (Post)" +
      "</label>" +
      '<input type="datetime-local" class="schedule-datetime-post" data-id="' +
      post.id +
      '" min="' +
      scheduleMin +
      '" value="" style="flex: 1; padding: 0.375rem 0.5rem; font-size: 0.8125rem; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface);" disabled/>' +
      // Schedule for STORY
      '<label style="display: flex; align-items: center; gap: 0.25rem; color: var(--text-muted); margin-left:0.5rem;">' +
      '<input type="checkbox" class="schedule-checkbox-story" data-id="' +
      post.id +
      '" ' +
      'style="margin: 0;" />' +
      "Zamanla (Story)" +
      "</label>" +
      '<input type="datetime-local" class="schedule-datetime-story" data-id="' +
      post.id +
      '" min="' +
      scheduleMin +
      '" value="" style="flex: 1; padding: 0.375rem 0.5rem; font-size: 0.8125rem; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface);" disabled/>' +
      "</div>" +
      "</div>" +
      "</article>"
    );
  }

  function loadPosts(status) {
    const url = status ? API_BASE + "/posts?status=" + encodeURIComponent(status) : API_BASE + "/posts";
    getJson(url)
      .then(function (list) {
        currentStatusFilter = status || "";
        if (!postsCards) return;
        postsCards.innerHTML = "";
        if (!list || list.length === 0) {
          if (postsEmpty) {
            postsEmpty.hidden = false;
            postsEmpty.textContent =
              status === "draft"
                ? "Taslak gönderi yok."
                : status === "approved"
                  ? "Onaylı gönderi yok."
                  : status === "published"
                    ? "Yayınlanmış gönderi yok."
                    : "Henüz gönderi yok. Yukarıdan yeni içerik üretebilirsiniz.";
          }
          return;
        }
        if (postsEmpty) postsEmpty.hidden = true;
        list.forEach(function (post) {
          postsCards.insertAdjacentHTML("beforeend", renderPostCard(post));
        });
        bindCardActions();
      })
      .catch(function () {
        if (postsCards) postsCards.innerHTML = "";
        if (postsEmpty) {
          postsEmpty.hidden = false;
          postsEmpty.textContent = "Gönderiler yüklenirken hata oluştu.";
        }
      });
  }

  function bindCardActions() {
    if (!postsCards) return;
    postsCards.querySelectorAll(".btn-approve").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id) return;
        btn.disabled = true;
        postJson(API_BASE + "/approve/" + id, {})
          .then(function () {
            loadPosts(currentStatusFilter);
          })
          .catch(function (err) {
            alert(err.message || "Onaylama başarısız.");
          })
          .finally(function () {
            btn.disabled = false;
          });
      });
    });
    postsCards.querySelectorAll(".btn-publish").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id) return;
        const card = btn.closest(".post-card");
        const status = card ? card.getAttribute("data-status") : null;
        const scheduleCheckbox = card ? card.querySelector('.schedule-checkbox-post[data-id="' + id + '"]') : null;
        const scheduleInput = card ? card.querySelector('.schedule-datetime-post[data-id="' + id + '"]') : null;
        let scheduledAt = null;
        if (scheduleCheckbox && scheduleCheckbox.checked && scheduleInput && scheduleInput.value) {
          try {
            const localDate = new Date(scheduleInput.value);
            if (isNaN(localDate.getTime())) {
              alert("Geçersiz tarih/saat seçildi.");
              btn.disabled = false;
              return;
            }
            scheduledAt = localDate.toISOString();
          } catch (e) {
            alert("Tarih/saat formatı hatası: " + e.message);
            btn.disabled = false;
            return;
          }
        }
        btn.disabled = true;
        // choose endpoint: republish for failed posts, publish otherwise
        let publishPromise;
        if (status === "failed") {
          // Use republish so backend will set approved then publish
          publishPromise = postJson(API_BASE + "/posts/" + id + "/republish", scheduledAt ? { post_type: "post", scheduled_at: scheduledAt } : { post_type: "post" });
        } else {
          // default publish
          publishPromise = postJson(API_BASE + "/publish/" + id, scheduledAt ? { scheduled_at: scheduledAt } : { post_type: "post", ...(scheduledAt ? { scheduled_at: scheduledAt } : {}) });
        }
        publishPromise
          .then(function (res) {
            if (res && res.success) {
              loadPosts(currentStatusFilter);
            } else if (res && res.error_message) {
              alert("Yayınlama hatası: " + res.error_message);
              loadPosts(currentStatusFilter);
            } else {
              loadPosts(currentStatusFilter);
            }
          })
          .catch(function (err) {
            alert(err.message || "Yayınlama başarısız.");
          })
          .finally(function () {
            btn.disabled = false;
          });
      });
    });
    postsCards.querySelectorAll(".btn-detail").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (id) openDetail(id);
      });
    });
    postsCards.querySelectorAll(".btn-publish-post").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id) return;
        const card = btn.closest(".post-card");
        const status = card ? card.getAttribute("data-status") : null;
        const scheduleCheckbox = card ? card.querySelector('.schedule-checkbox-post[data-id="' + id + '"]') : null;
        const scheduleInput = card ? card.querySelector('.schedule-datetime-post[data-id="' + id + '"]') : null;
        let scheduledAt = null;
        if (scheduleCheckbox && scheduleCheckbox.checked && scheduleInput && scheduleInput.value) {
          try {
            const localDate = new Date(scheduleInput.value);
            if (isNaN(localDate.getTime())) {
              alert("Geçersiz tarih/saat seçildi.");
              btn.disabled = false;
              return;
            }
            scheduledAt = localDate.toISOString();
          } catch (e) {
            alert("Tarih/saat formatı hatası: " + e.message);
            btn.disabled = false;
            return;
          }
        }
        btn.disabled = true;
        let publishPromisePost;
        if (status === "failed") {
          publishPromisePost = postJson(API_BASE + "/posts/" + id + "/republish", scheduledAt ? { post_type: "post", scheduled_at: scheduledAt } : { post_type: "post" });
        } else {
          publishPromisePost = postJson(API_BASE + "/publish/" + id, scheduledAt ? { post_type: "post", scheduled_at: scheduledAt } : { post_type: "post" });
        }
        publishPromisePost
          .then(function (res) {
            if (res && res.success) {
              loadPosts(currentStatusFilter);
            } else if (res && res.error_message) {
              alert("Yayınlama hatası: " + res.error_message);
              loadPosts(currentStatusFilter);
            } else {
              loadPosts(currentStatusFilter);
            }
          })
          .catch(function (err) {
            alert(err.message || "Yayınlama başarısız.");
          })
          .finally(function () {
            btn.disabled = false;
          });
      });
    });
    postsCards.querySelectorAll(".btn-publish-story").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id) return;
        const card = btn.closest(".post-card");
        const status = card ? card.getAttribute("data-status") : null;
        // Story publish doesn't use caption; scheduled stories are not supported here (optional)
        const scheduleCheckboxStory = card ? card.querySelector('.schedule-checkbox-story[data-id="' + id + '"]') : null;
        const scheduleInputStory = card ? card.querySelector('.schedule-datetime-story[data-id="' + id + '"]') : null;
        let scheduledAtStory = null;
        if (scheduleCheckboxStory && scheduleCheckboxStory.checked && scheduleInputStory && scheduleInputStory.value) {
          try {
            const localDate = new Date(scheduleInputStory.value);
            if (isNaN(localDate.getTime())) {
              alert("Geçersiz tarih/saat seçildi.");
              btn.disabled = false;
              return;
            }
            scheduledAtStory = localDate.toISOString();
          } catch (e) {
            alert("Tarih/saat formatı hatası: " + e.message);
            btn.disabled = false;
            return;
          }
        }
        btn.disabled = true;
        let publishPromiseStory;
        if (status === "failed") {
          publishPromiseStory = postJson(API_BASE + "/posts/" + id + "/republish", scheduledAtStory ? { post_type: "story", scheduled_at: scheduledAtStory } : { post_type: "story" });
        } else {
          publishPromiseStory = postJson(API_BASE + "/publish/" + id, scheduledAtStory ? { post_type: "story", scheduled_at: scheduledAtStory } : { post_type: "story" });
        }
        publishPromiseStory
          .then(function (res) {
            if (res && res.success) {
              loadPosts(currentStatusFilter);
            } else if (res && res.error_message) {
              alert("Yayınlama hatası: " + res.error_message);
              loadPosts(currentStatusFilter);
            } else {
              loadPosts(currentStatusFilter);
            }
          })
          .catch(function (err) {
            alert(err.message || "Story paylaşımı başarısız.");
          })
          .finally(function () {
            btn.disabled = false;
          });
      });
    });
    postsCards.querySelectorAll(".btn-delete-post").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id || !confirm("Bu gönderiyi silmek istediğinize emin misiniz?")) return;
        btn.disabled = true;
        deleteJson(API_BASE + "/posts/" + id)
          .then(function () {
            loadPosts(currentStatusFilter);
          })
          .catch(function (err) {
            alert(err.message || "Silme başarısız.");
          })
          .finally(function () {
            btn.disabled = false;
          });
      });
    });
    postsCards.querySelectorAll(".btn-republish").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = parseInt(btn.getAttribute("data-id"), 10);
        if (!id) return;
        const card = btn.closest(".post-card");
        if (!card) return;

        // If already replaced, do nothing
        if (card.querySelector(".republish-replace")) return;

        // Keep original button to restore later
        const originalBtn = btn;

        // Create replacement container that will replace the original "Yeniden Yayınla" button
        const replace = document.createElement("div");
        replace.className = "republish-replace";
        replace.style.display = "flex";
        replace.style.gap = "0.5rem";

        const btnPost = document.createElement("button");
        btnPost.className = "btn btn-success";
        btnPost.textContent = "Yayınla (Post)";

        const btnStory = document.createElement("button");
        btnStory.className = "btn btn-outline-success";
        btnStory.textContent = "Yayınla (Story)";

        const btnCancel = document.createElement("button");
        btnCancel.className = "btn btn-secondary";
        btnCancel.textContent = "İptal";

        replace.appendChild(btnPost);
        replace.appendChild(btnStory);
        replace.appendChild(btnCancel);

        // Replace the original button in the DOM
        originalBtn.parentNode.replaceChild(replace, originalBtn);

        const restore = () => {
          const cur = card.querySelector(".republish-replace");
          if (cur) cur.parentNode.replaceChild(originalBtn, cur);
          loadPosts(currentStatusFilter);
        };

        btnCancel.addEventListener("click", function () {
          restore();
        });

        const doPublish = (type) => {
          btnPost.disabled = true;
          btnStory.disabled = true;
          postJson(API_BASE + "/posts/" + id + "/republish", { post_type: type })
            .then((res) => {
              if (res && res.success) {
                restore();
              } else if (res && res.error_message) {
                alert("Yayınlama hatası: " + res.error_message);
                restore();
              } else {
                restore();
              }
            })
            .catch((err) => {
              alert(err.message || "Yayınlama başarısız.");
              restore();
            });
        };

        btnPost.addEventListener("click", function () {
          doPublish("post");
        });
        btnStory.addEventListener("click", function () {
          doPublish("story");
        });
      });
    });
    // Schedule checkbox toggle
    // Attach change listeners for both post and story schedule checkboxes
    postsCards.querySelectorAll(".schedule-checkbox-post, .schedule-checkbox-story").forEach(function (checkbox) {
      checkbox.addEventListener("change", function () {
        const id = parseInt(checkbox.getAttribute("data-id"), 10);
        const card = checkbox.closest(".post-card");
        const isPost = checkbox.classList.contains("schedule-checkbox-post");
        const scheduleInput = card ? card.querySelector((isPost ? '.schedule-datetime-post' : '.schedule-datetime-story') + '[data-id=\"' + id + '\"]') : null;
        if (scheduleInput) {
          scheduleInput.disabled = !checkbox.checked;
          if (checkbox.checked && !scheduleInput.value) {
            // Varsayılan: 1 saat sonra (yerel saat)
            const now = new Date();
            now.setHours(now.getHours() + 1);
            scheduleInput.value = toDatetimeLocalString(now);
            scheduleInput.min = scheduleInputMinValue();
          }
        }
      });
    });
  }

  // ——— Filter tabs ———
  document.querySelectorAll(".filter-tabs .tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".filter-tabs .tab").forEach(function (t) {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      const status = tab.getAttribute("data-status") || "";
      loadPosts(status);
    });
  });

  // ——— Modal (detail) ———
  const modal = document.getElementById("modal");
  const modalBody = document.getElementById("modal-body");

  function openDetail(postId) {
    getJson(API_BASE + "/posts/" + postId)
      .then(function (post) {
        if (!modal || !modalBody) return;
        const imgSrc = imageUrl(post.image_url || "");
        let html =
          '<p class="meta-line">ID: ' +
          escapeHtml(post.id) +
          " · " +
          statusBadge(post.status) +
          " · " +
          escapeHtml(formatDate(post.created_at)) +
          "</p>";
        if (imgSrc) {
          html += '<img src="' + escapeHtml(imgSrc) + '" alt="" />';
        }
        html += '<p class="caption-full">' + escapeHtml(post.caption || "—") + "</p>";
        if (post.hashtags) {
          html += '<p class="meta-line">Hashtag’ler: ' + escapeHtml(post.hashtags) + "</p>";
        }
        if (post.image_prompt) {
          html += '<p class="image-prompt">Görsel prompt: ' + escapeHtml(post.image_prompt) + "</p>";
        }
        modalBody.innerHTML = html;
        modal.hidden = false;
      })
      .catch(function (err) {
        alert(err.message || "Detay yüklenemedi.");
      });
  }

  function closeModal() {
    if (modal) modal.hidden = true;
  }

  modal &&
    modal.querySelectorAll("[data-close]").forEach(function (el) {
      el.addEventListener("click", closeModal);
    });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  // ——— Init ———
  loadPosts("");

  // ——— Automation settings UI ———
  const automationEnabled = document.getElementById("automation-enabled");
  const automationFrequency = document.getElementById("automation-frequency");
  const automationDailyCount = document.getElementById("automation-daily-count");
  const automationWeeklyCount = document.getElementById("automation-weekly-count");
  const automationStartHour = document.getElementById("automation-start-hour");
  const automationEndHour = document.getElementById("automation-end-hour");
  const automationOnlyDraft = document.getElementById("automation-only-draft");
  const btnAutomationSave = document.getElementById("btn-automation-save");
  const automationMessage = document.getElementById("automation-message");

  function loadAutomationSettings() {
    hideMessage(automationMessage);
    getJson(API_BASE + "/automation/settings")
      .then(function (res) {
        automationEnabled.checked = !!res.enabled;
        automationFrequency.value = res.frequency || "daily";
        if (automationDailyCount) automationDailyCount.value = res.daily_count || "";
        if (automationWeeklyCount) automationWeeklyCount.value = res.weekly_count || "";
        // convert hour integers (0-23) to time input value "HH:00" (only if inputs present)
        if (automationStartHour)
          automationStartHour.value = res.start_hour != null ? String(res.start_hour).padStart(2, "0") + ":00" : "";
        if (automationEndHour)
          automationEndHour.value = res.end_hour != null ? String(res.end_hour).padStart(2, "0") + ":00" : "";
        automationOnlyDraft.checked = !!res.only_draft;
        // daily_times and weekly_times rendering
        const dailyList = document.getElementById("automation-daily-list");
        const weeklyList = document.getElementById("automation-weekly-list");
        if (dailyList) dailyList.innerHTML = "";
        if (weeklyList) weeklyList.innerHTML = "";
        (res.daily_times || []).forEach(function (t) {
          if (dailyList) addDailyListItem(t);
        });
        (res.weekly_times || []).forEach(function (w) {
          if (weeklyList) addWeeklyListItem(w);
        });
        togglePanels();
      })
      .catch(function () {
        // no settings yet — keep defaults
      });
  }

  function saveAutomationSettings() {
    hideMessage(automationMessage);
    btnAutomationSave.disabled = true;
    function readHourFromInput(el) {
      if (!el) return null;
      var v = (el.value || "").trim();
      if (!v) return null;
      return v; // return "HH:MM" string to backend (backend accepts start_time/end_time)
    }

    const payload = {
      enabled: !!automationEnabled.checked,
      frequency: automationFrequency.value,
      daily_count: automationDailyCount.value ? parseInt(automationDailyCount.value, 10) : null,
      weekly_count: automationWeeklyCount.value ? parseInt(automationWeeklyCount.value, 10) : null,
      start_time: readHourFromInput(automationStartHour),
      end_time: readHourFromInput(automationEndHour),
      only_draft: !!automationOnlyDraft.checked,
    };
    postJson(API_BASE + "/automation/settings", payload)
      .then(function (res) {
        showMessage(automationMessage, "Ayarlar kaydedildi.", "success");
        // refresh UI with saved values
        loadAutomationSettings();
      })
      .catch(function (err) {
        showMessage(automationMessage, err.message || "Ayar kaydedilemedi.", "error");
      })
      .finally(function () {
        btnAutomationSave.disabled = false;
      });
  }

  if (btnAutomationSave) {
    btnAutomationSave.addEventListener("click", function () {
      saveAutomationSettings();
    });
    // load on init
    loadAutomationSettings();
  }

  // dynamic lists and panels
  function togglePanels() {
    const freq = automationFrequency.value;
    document.getElementById("automation-daily-panel").style.display = freq === "daily" ? "" : "none";
    document.getElementById("automation-weekly-panel").style.display = freq === "weekly" ? "" : "none";
  }
  automationFrequency && automationFrequency.addEventListener("change", togglePanels);

  function addDailyListItem(timeStr) {
    const list = document.getElementById("automation-daily-list");
    const el = document.createElement("div");
    el.className = "automation-time-item";
    // allow either string "HH:MM" or object {time: "HH:MM", auto_approve: bool}
    const item = typeof timeStr === "string" ? { time: timeStr, auto_approve: false } : timeStr || { time: "", auto_approve: false };
    // content: label | auto-approve checkbox | countdown | remove
    const label = document.createElement("span");
    label.className = "time-label";
    label.textContent = String(item.time);
    const autoChk = document.createElement("input");
    autoChk.type = "checkbox";
    autoChk.className = "time-auto-approve";
    autoChk.style.margin = "0 0.5rem";
    autoChk.checked = !!item.auto_approve;
    const autoLabel = document.createElement("label");
    autoLabel.style.display = "inline-flex";
    autoLabel.style.alignItems = "center";
    autoLabel.style.gap = "0.25rem";
    autoLabel.style.color = "var(--text-muted)";
    autoLabel.appendChild(autoChk);
    autoLabel.appendChild(document.createTextNode("Otomatik onayla"));
    // Auto-publish options (shown/enabled only when auto_approve is checked)
    const postPublishChk = document.createElement("input");
    postPublishChk.type = "checkbox";
    postPublishChk.className = "time-auto-publish-post";
    postPublishChk.style.margin = "0 0.25rem";
    postPublishChk.checked = !!item.auto_publish_post;
    const postPublishLabel = document.createElement("label");
    postPublishLabel.style.display = "inline-flex";
    postPublishLabel.style.alignItems = "center";
    postPublishLabel.style.gap = "0.25rem";
    postPublishLabel.style.color = "var(--text-muted)";
    postPublishLabel.appendChild(postPublishChk);
    postPublishLabel.appendChild(document.createTextNode("Otomatik yayınla (Post)"));

    const storyPublishChk = document.createElement("input");
    storyPublishChk.type = "checkbox";
    storyPublishChk.className = "time-auto-publish-story";
    storyPublishChk.style.margin = "0 0.25rem";
    storyPublishChk.checked = !!item.auto_publish_story;
    const storyPublishLabel = document.createElement("label");
    storyPublishLabel.style.display = "inline-flex";
    storyPublishLabel.style.alignItems = "center";
    storyPublishLabel.style.gap = "0.25rem";
    storyPublishLabel.style.color = "var(--text-muted)";
    storyPublishLabel.appendChild(storyPublishChk);
    storyPublishLabel.appendChild(document.createTextNode("Otomatik yayınla (Story)"));
    // Initially disable publish options if auto approval not checked
    postPublishChk.disabled = !autoChk.checked;
    storyPublishChk.disabled = !autoChk.checked;
    autoChk.addEventListener("change", function () {
      postPublishChk.disabled = !autoChk.checked;
      storyPublishChk.disabled = !autoChk.checked;
      if (!autoChk.checked) {
        postPublishChk.checked = false;
        storyPublishChk.checked = false;
      }
    });
    const countdown = document.createElement("span");
    countdown.className = "time-countdown";
    countdown.style.margin = "0 0.75rem";
    countdown.textContent = ""; // will be filled by timer
    const btn = document.createElement("button");
    btn.className = "btn btn-secondary btn-remove";
    btn.type = "button";
    btn.textContent = "Kaldır";
    el.appendChild(label);
    el.appendChild(autoLabel);
    el.appendChild(postPublishLabel);
    el.appendChild(storyPublishLabel);
    el.appendChild(countdown);
    el.appendChild(btn);
    list.appendChild(el);
    // start countdown timer for this daily time
    const timerId = startDailyCountdown(countdown, String(item.time));
    el.dataset.timerId = String(timerId);
    btn.addEventListener("click", function () {
      // clear timer
      try {
        const id = parseInt(el.dataset.timerId || "0", 10);
        if (id) clearInterval(id);
      } catch (e) {}
      el.remove();
    });
  }

  function addWeeklyListItem(obj) {
    const list = document.getElementById("automation-weekly-list");
    const el = document.createElement("div");
    el.className = "automation-time-item";
    const item = obj || { day: "", time: "", auto_approve: false };
    const label = document.createElement("span");
    label.className = "time-label";
    const labelText = (item.day || "") + " " + (item.time || "");
    label.textContent = labelText;
    const autoChk = document.createElement("input");
    autoChk.type = "checkbox";
    autoChk.className = "time-auto-approve";
    autoChk.style.margin = "0 0.5rem";
    autoChk.checked = !!item.auto_approve;
    const autoLabel = document.createElement("label");
    autoLabel.style.display = "inline-flex";
    autoLabel.style.alignItems = "center";
    autoLabel.style.gap = "0.25rem";
    autoLabel.style.color = "var(--text-muted)";
    autoLabel.appendChild(autoChk);
    autoLabel.appendChild(document.createTextNode("Otomatik onayla"));
    const postPublishChk = document.createElement("input");
    postPublishChk.type = "checkbox";
    postPublishChk.className = "time-auto-publish-post";
    postPublishChk.style.margin = "0 0.25rem";
    postPublishChk.checked = !!item.auto_publish_post;
    const postPublishLabel = document.createElement("label");
    postPublishLabel.style.display = "inline-flex";
    postPublishLabel.style.alignItems = "center";
    postPublishLabel.style.gap = "0.25rem";
    postPublishLabel.style.color = "var(--text-muted)";
    postPublishLabel.appendChild(postPublishChk);
    postPublishLabel.appendChild(document.createTextNode("Otomatik yayınla (Post)"));
    const storyPublishChk = document.createElement("input");
    storyPublishChk.type = "checkbox";
    storyPublishChk.className = "time-auto-publish-story";
    storyPublishChk.style.margin = "0 0.25rem";
    storyPublishChk.checked = !!item.auto_publish_story;
    const storyPublishLabel = document.createElement("label");
    storyPublishLabel.style.display = "inline-flex";
    storyPublishLabel.style.alignItems = "center";
    storyPublishLabel.style.gap = "0.25rem";
    storyPublishLabel.style.color = "var(--text-muted)";
    storyPublishLabel.appendChild(storyPublishChk);
    storyPublishLabel.appendChild(document.createTextNode("Otomatik yayınla (Story)"));
    postPublishChk.disabled = !autoChk.checked;
    storyPublishChk.disabled = !autoChk.checked;
    autoChk.addEventListener("change", function () {
      postPublishChk.disabled = !autoChk.checked;
      storyPublishChk.disabled = !autoChk.checked;
      if (!autoChk.checked) {
        postPublishChk.checked = false;
        storyPublishChk.checked = false;
      }
    });
    const countdown = document.createElement("span");
    countdown.className = "time-countdown";
    countdown.style.margin = "0 0.75rem";
    countdown.textContent = "";
    const btn = document.createElement("button");
    btn.className = "btn btn-secondary btn-remove";
    btn.type = "button";
    btn.textContent = "Kaldır";
    el.appendChild(label);
    el.appendChild(autoLabel);
    el.appendChild(postPublishLabel);
    el.appendChild(storyPublishLabel);
    el.appendChild(countdown);
    el.appendChild(btn);
    list.appendChild(el);
    // start weekly countdown
    const timerId = startWeeklyCountdown(countdown, item);
    el.dataset.timerId = String(timerId);
    btn.addEventListener("click", function () {
      try {
        const id = parseInt(el.dataset.timerId || "0", 10);
        if (id) clearInterval(id);
      } catch (e) {}
      el.remove();
    });
  }

  // Countdown helpers
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function formatRemaining(sec) {
    if (sec <= 0) return "00:00:00";
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = Math.floor(sec % 60);
    return pad(h) + ":" + pad(m) + ":" + pad(s);
  }

  function startDailyCountdown(el, timeStr) {
    function computeSec() {
      try {
        var parts = String(timeStr).split(":");
        var hh = parseInt(parts[0], 10) || 0;
        var mm = parts.length > 1 ? parseInt(parts[1], 10) || 0 : 0;
        var now = new Date();
        var target = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hh, mm, 0);
        if (target <= now) {
          // next day
          target = new Date(target.getTime() + 24 * 3600 * 1000);
        }
        return Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000));
      } catch (e) {
        return 0;
      }
    }
    el.textContent = formatRemaining(computeSec());
    var id = setInterval(function () {
      el.textContent = formatRemaining(computeSec());
    }, 1000);
    return id;
  }

  function startWeeklyCountdown(el, obj) {
    function computeSec() {
      try {
        var now = new Date();
        var weekdayMap = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0 };
        var dayCode = (obj && obj.day) || "";
        var timeStr = (obj && obj.time) || "";
        var targetWd = weekdayMap[dayCode];
        if (targetWd === undefined) return 0;
        // find next date with that weekday
        var daysAhead = (targetWd - now.getDay() + 7) % 7;
        var parts = String(timeStr).split(":");
        var hh = parseInt(parts[0], 10) || 0;
        var mm = parts.length > 1 ? parseInt(parts[1], 10) || 0 : 0;
        var target = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysAhead, hh, mm, 0);
        if (target <= now) {
          // next week
          target = new Date(target.getTime() + 7 * 24 * 3600 * 1000);
        }
        return Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000));
      } catch (e) {
        return 0;
      }
    }
    el.textContent = formatRemaining(computeSec());
    var id = setInterval(function () {
      el.textContent = formatRemaining(computeSec());
    }, 1000);
    return id;
  }

  document.getElementById("btn-add-daily-time")?.addEventListener("click", function () {
    const t = document.getElementById("automation-daily-time").value;
    if (!t) return alert("Lütfen saat seçin.");
    addDailyListItem(t);
  });
  document.getElementById("btn-add-weekly-time")?.addEventListener("click", function () {
    const day = document.getElementById("automation-weekday").value;
    const t = document.getElementById("automation-weekly-time").value;
    if (!t) return alert("Lütfen saat seçin.");
    addWeeklyListItem({ day: day, time: t });
  });

  // Delegated remove handlers (works even if buttons created elsewhere)
  (function attachDelegatedRemovers() {
    const dailyList = document.getElementById("automation-daily-list");
    const weeklyList = document.getElementById("automation-weekly-list");
    if (dailyList) {
      dailyList.addEventListener("click", function (ev) {
        const btn = ev.target.closest && ev.target.closest(".btn-remove");
        if (!btn) return;
        const item = btn.closest(".automation-time-item");
        if (!item) return;
        try {
          const id = parseInt(item.dataset.timerId || "0", 10);
          if (id) clearInterval(id);
        } catch (e) {}
        item.remove();
      });
    }
    if (weeklyList) {
      weeklyList.addEventListener("click", function (ev) {
        const btn = ev.target.closest && ev.target.closest(".btn-remove");
        if (!btn) return;
        const item = btn.closest(".automation-time-item");
        if (!item) return;
        try {
          const id = parseInt(item.dataset.timerId || "0", 10);
          if (id) clearInterval(id);
        } catch (e) {}
        item.remove();
      });
    }
  })();

  // modify saveAutomationSettings to collect lists
  const origSave = saveAutomationSettings;
  saveAutomationSettings = function () {
    // collect daily and weekly lists into payload before saving
    const daily = Array.from(document.querySelectorAll("#automation-daily-list .automation-time-item")).map((el) => {
      const timeLabel = el.querySelector(".time-label");
      const chk = el.querySelector(".time-auto-approve");
      const postChk = el.querySelector(".time-auto-publish-post");
      const storyChk = el.querySelector(".time-auto-publish-story");
      return {
        time: timeLabel ? (timeLabel.textContent || "").trim() : "",
        auto_approve: !!(chk && chk.checked),
        auto_publish_post: !!(postChk && postChk.checked),
        auto_publish_story: !!(storyChk && storyChk.checked),
      };
    });
    const weekly = Array.from(document.querySelectorAll("#automation-weekly-list .automation-time-item")).map((el) => {
      const timeLabel = el.querySelector(".time-label");
      const chk = el.querySelector(".time-auto-approve");
      const postChk = el.querySelector(".time-auto-publish-post");
      const storyChk = el.querySelector(".time-auto-publish-story");
      const txt = timeLabel ? (timeLabel.textContent || "").trim() : "";
      const parts = txt.split(" ");
      return {
        day: parts[0] || "",
        time: parts[1] || "",
        auto_approve: !!(chk && chk.checked),
        auto_publish_post: !!(postChk && postChk.checked),
        auto_publish_story: !!(storyChk && storyChk.checked),
      };
    });
    // attach to payload via closure trick: call inner function
    hideMessage(automationMessage);
    btnAutomationSave.disabled = true;
    function readHourFromInput(el) {
      if (!el) return null;
      var v = (el.value || "").trim();
      if (!v) return null;
      return v;
    }
    const payload = {
      enabled: !!(automationEnabled && automationEnabled.checked),
      frequency: automationFrequency ? automationFrequency.value : "daily",
      daily_count: automationDailyCount && automationDailyCount.value ? parseInt(automationDailyCount.value, 10) : null,
      weekly_count: automationWeeklyCount && automationWeeklyCount.value ? parseInt(automationWeeklyCount.value, 10) : null,
      start_time: readHourFromInput(automationStartHour),
      end_time: readHourFromInput(automationEndHour),
      only_draft: !!(automationOnlyDraft && automationOnlyDraft.checked),
      daily_times: daily,
      weekly_times: weekly,
    };
    postJson(API_BASE + "/automation/settings", payload)
      .then(function (res) {
        showMessage(automationMessage, "Ayarlar kaydedildi.", "success");
        loadAutomationSettings();
      })
      .catch(function (err) {
        showMessage(automationMessage, err.message || "Ayar kaydedilemedi.", "error");
      })
      .finally(function () {
        btnAutomationSave.disabled = false;
      });
  };
})();
