// ─── Kanban Board JS (integrated into WaaS Portal) ──────────────
let boardData = [];
let currentCard = null;

const API = '/admin/kanban';

// ─── Init ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadBoard();
    setupModalEvents();
    setupHeaderEvents();
});

async function loadBoard() {
    const res = await fetch(`${API}/api/board`);
    boardData = await res.json();
    renderBoard();
}

// ─── Render Board ────────────────────────────────────────────────
function renderBoard() {
    const board = document.getElementById('kbBoard');
    board.innerHTML = '';

    boardData.forEach(col => {
        board.appendChild(createColumnElement(col));
    });

    new Sortable(board, {
        animation: 200,
        handle: '.column-header',
        draggable: '.kb-column',
        ghostClass: 'dragging-column',
        chosenClass: 'chosen-column',
        dragClass: 'drag-column',
        direction: 'horizontal',
        onEnd: function (evt) {
            const newOrder = [...board.querySelectorAll('.kb-column')].map(
                c => c.dataset.columnId
            );
            fetch(`${API}/api/columns/reorder`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ column_ids: newOrder })
            }).then(() => loadBoard());
        }
    });

    document.querySelectorAll('.card-list').forEach(cardList => {
        new Sortable(cardList, {
            group: 'cards',
            animation: 200,
            draggable: '.kb-card',
            ghostClass: 'card-ghost',
            chosenClass: 'card-chosen',
            dragClass: 'card-drag',
            fallbackOnBody: true,
            swapThreshold: 0.65,
            onEnd: function (evt) {
                const cardId = evt.item.dataset.cardId;
                const newColumnId = evt.to.dataset.columnId;
                const cardUpdates = [];

                evt.to.querySelectorAll('.kb-card').forEach((c, i) => {
                    cardUpdates.push({
                        id: c.dataset.cardId,
                        column_id: newColumnId,
                        position: i
                    });
                });

                if (evt.from !== evt.to) {
                    const srcColumnId = evt.from.dataset.columnId;
                    evt.from.querySelectorAll('.kb-card').forEach((c, i) => {
                        cardUpdates.push({
                            id: c.dataset.cardId,
                            column_id: srcColumnId,
                            position: i
                        });
                    });
                }

                fetch(`${API}/api/cards/reorder`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cards: cardUpdates })
                }).then(() => loadBoard());
            }
        });
    });
}

function createColumnElement(col) {
    const el = document.createElement('div');
    el.className = 'kb-column';
    el.dataset.columnId = col.id;

    const headerWrap = document.createElement('div');
    headerWrap.className = 'column-header-wrap';

    const header = document.createElement('div');
    header.className = 'column-header';

    const title = document.createElement('span');
    title.className = 'column-title';
    title.textContent = col.title;
    title.addEventListener('click', () => openRenameModal(col));

    const count = document.createElement('span');
    count.className = 'column-count';
    count.textContent = (col.cards || []).length;

    const menuBtn = document.createElement('button');
    menuBtn.className = 'column-menu-btn';
    menuBtn.innerHTML = '&#8943;';
    menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllMenus();
        const menu = headerWrap.querySelector('.column-menu');
        menu.classList.toggle('show');
    });

    header.appendChild(title);
    header.appendChild(count);
    header.appendChild(menuBtn);
    headerWrap.appendChild(header);

    const menu = document.createElement('div');
    menu.className = 'column-menu';

    const renameItem = document.createElement('button');
    renameItem.className = 'column-menu-item';
    renameItem.textContent = 'Rename List';
    renameItem.addEventListener('click', () => {
        closeAllMenus();
        openRenameModal(col);
    });

    const deleteItem = document.createElement('button');
    deleteItem.className = 'column-menu-item danger';
    deleteItem.textContent = 'Delete List';
    deleteItem.addEventListener('click', () => {
        closeAllMenus();
        if (confirm(`Delete "${col.title}" and all its cards?`)) {
            deleteColumn(col.id);
        }
    });

    menu.appendChild(renameItem);
    menu.appendChild(deleteItem);
    headerWrap.appendChild(menu);
    el.appendChild(headerWrap);

    const cardList = document.createElement('div');
    cardList.className = 'card-list';
    cardList.dataset.columnId = col.id;

    (col.cards || []).forEach(card => {
        cardList.appendChild(createCardElement(card));
    });

    el.appendChild(cardList);

    // Add card area
    const addArea = document.createElement('div');
    addArea.className = 'add-card-area';

    const addBtn = document.createElement('button');
    addBtn.className = 'btn-add-card';
    addBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        Add a card
    `;

    const addForm = document.createElement('div');
    addForm.className = 'add-card-form';

    const addInput = document.createElement('textarea');
    addInput.className = 'add-card-input';
    addInput.placeholder = 'Enter a title for this card...';

    const addActions = document.createElement('div');
    addActions.className = 'add-card-actions';

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn-add-card-submit';
    submitBtn.textContent = 'Add Card';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn-add-card-cancel';
    cancelBtn.innerHTML = '&times;';

    addActions.appendChild(submitBtn);
    addActions.appendChild(cancelBtn);
    addForm.appendChild(addInput);
    addForm.appendChild(addActions);

    addBtn.addEventListener('click', () => {
        addBtn.style.display = 'none';
        addForm.classList.add('active');
        addInput.focus();
    });

    cancelBtn.addEventListener('click', () => {
        addForm.classList.remove('active');
        addBtn.style.display = 'flex';
        addInput.value = '';
    });

    submitBtn.addEventListener('click', () => {
        const t = addInput.value.trim();
        if (t) {
            createCard(col.id, t);
            addInput.value = '';
            addInput.focus();
        }
    });

    addInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitBtn.click(); }
        if (e.key === 'Escape') cancelBtn.click();
    });

    addArea.appendChild(addBtn);
    addArea.appendChild(addForm);
    el.appendChild(addArea);

    return el;
}

function createCardElement(card) {
    const el = document.createElement('div');
    el.className = 'kb-card';
    el.dataset.cardId = card.id;

    // Labels
    let labels = [];
    try { labels = JSON.parse(card.labels || '[]'); } catch (e) { labels = []; }
    if (labels.length > 0) {
        const labelsDiv = document.createElement('div');
        labelsDiv.className = 'card-labels';
        labels.forEach(color => {
            const chip = document.createElement('span');
            chip.className = 'card-label';
            chip.style.background = color;
            labelsDiv.appendChild(chip);
        });
        el.appendChild(labelsDiv);
    }

    // Card ID badge
    const idBadge = document.createElement('div');
    idBadge.className = 'card-id';
    idBadge.textContent = card.card_number ? `#${card.card_number}` : '';
    el.appendChild(idBadge);

    // Title
    const titleEl = document.createElement('div');
    titleEl.className = 'card-title';
    titleEl.textContent = card.title;
    el.appendChild(titleEl);

    // Description indicator
    if (card.description && card.description.trim()) {
        const indicator = document.createElement('div');
        indicator.className = 'card-desc-indicator';
        indicator.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>
            </svg>
        `;
        el.appendChild(indicator);
    }

    // Prospect link badge
    if (card.prospect_id) {
        const link = document.createElement('a');
        link.className = 'card-prospect-link';
        link.href = `/admin/prospects/${card.prospect_id}`;
        link.textContent = 'Prospect linked';
        link.addEventListener('click', (e) => e.stopPropagation());
        el.appendChild(link);
    }

    // Click to open detail
    el.addEventListener('mousedown', () => { el._wasDragged = false; });
    el.addEventListener('mousemove', () => { el._wasDragged = true; });
    el.addEventListener('click', () => {
        if (!el._wasDragged) openCardModal(card);
    });

    return el;
}

// ─── Close menus on outside click ────────────────────────────────
document.addEventListener('click', () => closeAllMenus());

function closeAllMenus() {
    document.querySelectorAll('.column-menu.show').forEach(m => m.classList.remove('show'));
}

// ─── API Calls ───────────────────────────────────────────────────
async function createCard(columnId, title) {
    await fetch(`${API}/api/cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column_id: columnId, title })
    });
    loadBoard();
}

async function deleteColumn(colId) {
    await fetch(`${API}/api/columns/${colId}`, { method: 'DELETE' });
    loadBoard();
}

async function renameColumn(colId, newTitle) {
    await fetch(`${API}/api/columns/${colId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle })
    });
    loadBoard();
}

async function addColumn(title) {
    await fetch(`${API}/api/columns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    });
    loadBoard();
}

// ─── Card Modal ──────────────────────────────────────────────────
function openCardModal(card) {
    currentCard = card;
    const overlay = document.getElementById('kbModalOverlay');
    const titleInput = document.getElementById('kbModalTitle');
    const descArea = document.getElementById('kbModalDescription');
    const colSpan = document.getElementById('kbModalColumn');
    const createdSpan = document.getElementById('kbModalCreated');
    const moveSelect = document.getElementById('kbModalMoveSelect');

    titleInput.value = card.title;
    descArea.value = card.description || '';

    const col = boardData.find(c => c.id === card.column_id);
    colSpan.textContent = `in list "${col ? col.title : ''}"`;
    const cardLabel = card.card_number ? `Card #${card.card_number}` : '';
    createdSpan.textContent = card.created_at
        ? `Created: ${new Date(card.created_at).toLocaleDateString()} - ${cardLabel}`
        : cardLabel;

    // Move-to dropdown
    moveSelect.innerHTML = '';
    boardData.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.title;
        if (c.id === card.column_id) opt.selected = true;
        moveSelect.appendChild(opt);
    });

    // Labels
    let labels = [];
    try { labels = JSON.parse(card.labels || '[]'); } catch (e) { labels = []; }
    renderLabelChips(labels);

    // Prospect button
    updateProspectButton(card);

    // Reset to preview mode
    showPreviewMode();
    updatePreview();

    // Load comments
    loadComments(card.id);

    document.getElementById('kbCommentAuthor').value = '';
    document.getElementById('kbCommentText').value = '';

    overlay.classList.add('show');
}

function updateProspectButton(card) {
    const container = document.getElementById('kbProspectAction');
    container.innerHTML = '';

    if (card.prospect_id) {
        const linked = document.createElement('div');
        linked.className = 'kb-prospect-linked';
        linked.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            Prospect linked — <a href="/admin/prospects/${card.prospect_id}">View prospect</a>
        `;
        container.appendChild(linked);
    } else {
        const btn = document.createElement('button');
        btn.className = 'kb-btn-prospect';
        btn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="8.5" cy="7" r="4"/>
                <line x1="20" y1="8" x2="20" y2="14"/>
                <line x1="23" y1="11" x2="17" y2="11"/>
            </svg>
            Create prospect
        `;
        btn.addEventListener('click', () => createProspectFromCard(card.id, btn));
        container.appendChild(btn);
    }
}

async function createProspectFromCard(cardId, btn) {
    btn.disabled = true;
    btn.textContent = 'Creating...';

    try {
        const res = await fetch(`${API}/api/cards/${cardId}/create-prospect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();

        if (res.ok) {
            currentCard.prospect_id = data.prospect_id;
            updateProspectButton(currentCard);
            loadBoard();
        } else {
            alert(data.error || 'Failed to create prospect');
            btn.disabled = false;
            btn.textContent = 'Create prospect';
        }
    } catch (err) {
        alert('Error creating prospect: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'Create prospect';
    }
}

function renderLabelChips(labels) {
    const container = document.getElementById('kbLabelChips');
    container.innerHTML = '';
    labels.forEach((color, idx) => {
        const chip = document.createElement('div');
        chip.className = 'label-chip';
        chip.style.background = color;
        chip.title = 'Click to remove';
        chip.addEventListener('click', () => {
            labels.splice(idx, 1);
            renderLabelChips(labels);
        });
        container.appendChild(chip);
    });
}

function showEditMode() {
    document.getElementById('kbModalDescription').style.display = 'block';
    document.getElementById('kbModalPreview').style.display = 'none';
    document.getElementById('kbBtnEdit').classList.add('active');
    document.getElementById('kbBtnPreview').classList.remove('active');
}

function showPreviewMode() {
    updatePreview();
    document.getElementById('kbModalDescription').style.display = 'none';
    document.getElementById('kbModalPreview').style.display = 'block';
    document.getElementById('kbBtnPreview').classList.add('active');
    document.getElementById('kbBtnEdit').classList.remove('active');
}

function updatePreview() {
    const desc = document.getElementById('kbModalDescription').value;
    const preview = document.getElementById('kbModalPreview');
    if (typeof marked !== 'undefined') {
        preview.innerHTML = marked.parse(desc || '*No description yet*');
    } else {
        preview.textContent = desc;
    }
}

function setupModalEvents() {
    const overlay = document.getElementById('kbModalOverlay');
    const closeBtn = document.getElementById('kbModalClose');
    const saveBtn = document.getElementById('kbModalSave');
    const deleteBtn = document.getElementById('kbModalDelete');
    const editBtn = document.getElementById('kbBtnEdit');
    const previewBtn = document.getElementById('kbBtnPreview');
    const addLabelBtn = document.getElementById('kbAddLabelBtn');
    const labelPicker = document.getElementById('kbLabelPicker');

    closeBtn.addEventListener('click', () => {
        overlay.classList.remove('show');
        currentCard = null;
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.classList.remove('show');
            currentCard = null;
        }
    });

    editBtn.addEventListener('click', showEditMode);
    previewBtn.addEventListener('click', showPreviewMode);

    addLabelBtn.addEventListener('click', () => {
        labelPicker.style.display = labelPicker.style.display === 'none' ? 'flex' : 'none';
    });

    document.getElementById('kbAddCommentBtn').addEventListener('click', submitComment);
    document.getElementById('kbCommentText').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitComment(); }
    });

    labelPicker.querySelectorAll('.label-color').forEach(colorEl => {
        colorEl.addEventListener('click', () => {
            const color = colorEl.dataset.color;
            const labels = getCurrentLabels();
            if (!labels.includes(color)) {
                labels.push(color);
                renderLabelChips(labels);
            }
            labelPicker.style.display = 'none';
        });
    });

    // Save card
    saveBtn.addEventListener('click', async () => {
        if (!currentCard) return;
        const title = document.getElementById('kbModalTitle').value.trim();
        const description = document.getElementById('kbModalDescription').value;
        const column_id = document.getElementById('kbModalMoveSelect').value;
        const labels = JSON.stringify(getCurrentLabels());

        await fetch(`${API}/api/cards/${currentCard.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, description, column_id, labels })
        });

        overlay.classList.remove('show');
        currentCard = null;
        loadBoard();
    });

    // Delete card
    deleteBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!currentCard) return;
        if (confirm('Delete this card?')) {
            await fetch(`${API}/api/cards/${currentCard.id}`, { method: 'DELETE' });
            overlay.classList.remove('show');
            currentCard = null;
            loadBoard();
        }
    });

    // Escape to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (overlay.classList.contains('show')) {
                overlay.classList.remove('show');
                currentCard = null;
            }
            const addColOverlay = document.getElementById('kbAddColumnOverlay');
            if (addColOverlay.style.display === 'flex') addColOverlay.style.display = 'none';
            const renameOvl = document.getElementById('kbRenameOverlay');
            if (renameOvl.style.display === 'flex') renameOvl.style.display = 'none';
            const settingsOvl = document.getElementById('kbSettingsOverlay');
            if (settingsOvl.style.display === 'flex') settingsOvl.style.display = 'none';
        }
    });

    // Rename Column Modal
    const renameOverlay = document.getElementById('kbRenameOverlay');
    document.getElementById('kbRenameClose').addEventListener('click', () => {
        renameOverlay.style.display = 'none';
    });
    renameOverlay.addEventListener('click', (e) => {
        if (e.target === renameOverlay) renameOverlay.style.display = 'none';
    });

    // Add Column Modal
    const addColOverlay = document.getElementById('kbAddColumnOverlay');
    const addColInput = document.getElementById('kbAddColumnInput');
    const addColSave = document.getElementById('kbAddColumnSave');
    const addColCancel = document.getElementById('kbAddColumnCancel');
    const addColClose = document.getElementById('kbAddColumnClose');

    addColClose.addEventListener('click', () => { addColOverlay.style.display = 'none'; });
    addColCancel.addEventListener('click', () => { addColOverlay.style.display = 'none'; });
    addColOverlay.addEventListener('click', (e) => {
        if (e.target === addColOverlay) addColOverlay.style.display = 'none';
    });

    addColSave.addEventListener('click', () => {
        const t = addColInput.value.trim();
        if (t) {
            addColumn(t);
            addColInput.value = '';
            addColOverlay.style.display = 'none';
        }
    });

    addColInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') addColSave.click();
        if (e.key === 'Escape') addColOverlay.style.display = 'none';
    });
}

function getCurrentLabels() {
    const chips = document.getElementById('kbLabelChips').querySelectorAll('.label-chip');
    return [...chips].map(c => {
        const bg = c.style.background || c.style.backgroundColor;
        return rgbToHex(bg);
    });
}

function rgbToHex(color) {
    if (color.startsWith('#')) return color;
    const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
        return '#' + [match[1], match[2], match[3]].map(x => {
            const hex = parseInt(x).toString(16);
            return hex.length === 1 ? '0' + hex : hex;
        }).join('');
    }
    return color;
}

function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}` : hex;
}

// ─── Comments ────────────────────────────────────────────────────
async function loadComments(cardId) {
    try {
        const res = await fetch(`${API}/api/cards/${cardId}/comments`);
        if (!res.ok) throw new Error('Failed to fetch comments');
        const comments = await res.json();
        renderComments(comments);
    } catch (error) {
        console.error('Error loading comments:', error);
        renderComments([]);
    }
}

function renderComments(comments) {
    const container = document.getElementById('kbCommentsList');
    container.innerHTML = '';

    if (!comments || comments.length === 0) {
        const emptyMsg = document.createElement('div');
        emptyMsg.className = 'comment-no-comments';
        emptyMsg.textContent = 'No comments yet. Be the first to comment!';
        container.appendChild(emptyMsg);
        return;
    }

    comments.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

    comments.forEach(comment => {
        const item = document.createElement('div');
        item.className = 'comment-item';

        const header = document.createElement('div');
        header.className = 'comment-header';

        const author = document.createElement('span');
        author.className = 'comment-author';
        author.textContent = comment.author || 'Anonymous';

        const timestamp = document.createElement('span');
        timestamp.className = 'comment-timestamp';
        timestamp.textContent = formatCommentTime(comment.created_at);

        header.appendChild(author);
        header.appendChild(timestamp);

        const text = document.createElement('div');
        text.className = 'comment-text';
        text.textContent = comment.text;

        item.appendChild(header);
        item.appendChild(text);
        container.appendChild(item);
    });
}

function formatCommentTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) return 'just now';
    if (diffMins === 1) return '1 minute ago';
    if (diffMins < 60) return `${diffMins} minutes ago`;
    if (diffHours === 1) return '1 hour ago';
    if (diffHours < 24) return `${diffHours} hours ago`;
    if (diffDays === 1) return 'yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString();
}

async function submitComment() {
    if (!currentCard) return;

    const authorInput = document.getElementById('kbCommentAuthor');
    const textInput = document.getElementById('kbCommentText');
    const author = authorInput.value.trim() || 'Anonymous';
    const text = textInput.value.trim();

    if (!text) return;

    try {
        const res = await fetch(`${API}/api/cards/${currentCard.id}/comments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ author, text })
        });

        if (!res.ok) throw new Error('Failed to add comment');
        textInput.value = '';
        await loadComments(currentCard.id);
    } catch (error) {
        console.error('Error submitting comment:', error);
        alert('Failed to add comment. Please try again.');
    }
}

// ─── Rename Column Modal ─────────────────────────────────────────
let renameColumnId = null;

function openRenameModal(col) {
    renameColumnId = col.id;
    const overlay = document.getElementById('kbRenameOverlay');
    const input = document.getElementById('kbRenameInput');
    input.value = col.title;
    overlay.style.display = 'flex';
    setTimeout(() => input.focus(), 100);

    const saveBtn = document.getElementById('kbRenameSave');
    const newSave = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newSave, saveBtn);
    newSave.addEventListener('click', () => {
        const newTitle = input.value.trim();
        if (newTitle && renameColumnId) {
            renameColumn(renameColumnId, newTitle);
        }
        overlay.style.display = 'none';
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') newSave.click();
        if (e.key === 'Escape') overlay.style.display = 'none';
    });
}

// ─── Header Events ───────────────────────────────────────────────
function setupHeaderEvents() {
    document.getElementById('kbAddColumnBtn').addEventListener('click', () => {
        const overlay = document.getElementById('kbAddColumnOverlay');
        const input = document.getElementById('kbAddColumnInput');
        input.value = '';
        overlay.style.display = 'flex';
        setTimeout(() => input.focus(), 100);
    });

    const settingsBtn = document.getElementById('kbSettingsBtn');
    const settingsOverlay = document.getElementById('kbSettingsOverlay');
    const settingsClose = document.getElementById('kbSettingsClose');
    const settingsSave = document.getElementById('kbSettingsSave');
    const boardNameInput = document.getElementById('kbBoardNameInput');
    const bgUpload = document.getElementById('kbBgUpload');

    settingsBtn.addEventListener('click', () => {
        boardNameInput.value = document.querySelector('.board-title').textContent;
        settingsOverlay.style.display = 'flex';
    });

    settingsClose.addEventListener('click', () => { settingsOverlay.style.display = 'none'; });
    settingsOverlay.addEventListener('click', (e) => {
        if (e.target === settingsOverlay) settingsOverlay.style.display = 'none';
    });

    settingsSave.addEventListener('click', () => {
        const newName = boardNameInput.value.trim();
        if (newName) {
            document.querySelector('.board-title').textContent = newName;
        }
        settingsOverlay.style.display = 'none';
    });

    document.querySelectorAll('.bg-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const color = btn.dataset.bg;
            document.getElementById('kbBoard').style.background = color;
            localStorage.setItem('kanbanBg', color);
            localStorage.removeItem('kanbanBgImage');
            document.querySelectorAll('.bg-option').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
        });
    });

    bgUpload.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (event) => {
                const imgUrl = event.target.result;
                document.getElementById('kbBoard').style.background = `url(${imgUrl}) center/cover no-repeat`;
                localStorage.setItem('kanbanBgImage', imgUrl);
            };
            reader.readAsDataURL(file);
        }
    });

    // Load saved background
    const savedBgImage = localStorage.getItem('kanbanBgImage');
    const savedBg = localStorage.getItem('kanbanBg');
    if (savedBgImage) {
        document.getElementById('kbBoard').style.background = `url(${savedBgImage}) center/cover no-repeat`;
    } else if (savedBg) {
        document.getElementById('kbBoard').style.background = savedBg;
    }

    const boardTitle = document.querySelector('.board-title');
    if (boardTitle) {
        boardTitle.style.cursor = 'pointer';
        boardTitle.addEventListener('click', () => settingsBtn.click());
    }
}
