/**
 * Quick Actions Floating Menu
 * Mounts inside #fabBoltMount (see base.html #fabDock) so alignment matches other FABs.
 */
class QuickActionsMenu {
    constructor() {
        this.isOpen = false;
        this.button = null;
        this.menu = null;
        this.mount = null;
        this.wrap = null;
        this.actions = this.defineActions();
        this.init();
    }

    init() {
        this.createButton();
        this.createMenu();
        this.attachGlobalListeners();
        this.attachButtonListener();
    }

    defineActions() {
        return [
            {
                id: 'start-timer',
                icon: 'fas fa-play',
                label: 'Start Timer',
                color: 'bg-green-500 hover:bg-green-600',
                action: () => this.startTimer(),
                shortcut: 't s'
            },
            {
                id: 'log-time',
                icon: 'fas fa-clock',
                label: 'Log Time',
                color: 'bg-blue-500 hover:bg-blue-600',
                action: () => { window.location.href = '/timer/manual_entry'; },
                shortcut: 't l'
            },
            {
                id: 'new-project',
                icon: 'fas fa-folder-plus',
                label: 'New Project',
                color: 'bg-purple-500 hover:bg-purple-600',
                action: () => { window.location.href = '/projects/create'; },
                shortcut: 'c p'
            },
            {
                id: 'new-task',
                icon: 'fas fa-tasks',
                label: 'New Task',
                color: 'bg-orange-500 hover:bg-orange-600',
                action: () => { window.location.href = '/tasks/create'; },
                shortcut: 'c t'
            },
            {
                id: 'new-client',
                icon: 'fas fa-user-plus',
                label: 'New Client',
                color: 'bg-indigo-500 hover:bg-indigo-600',
                action: () => { window.location.href = '/clients/create'; },
                shortcut: 'c c'
            },
            {
                id: 'quick-report',
                icon: 'fas fa-chart-line',
                label: 'Quick Report',
                color: 'bg-pink-500 hover:bg-pink-600',
                action: () => { window.location.href = '/reports/'; },
                shortcut: 'g r'
            }
        ];
    }

    createButton() {
        const mount = document.getElementById('fabBoltMount');
        this.mount = mount;
        this.wrap = document.createElement('div');
        this.wrap.className = 'relative flex shrink-0 flex-col items-end';
        Object.assign(this.wrap.style, {
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            flexShrink: '0'
        });
        this.button = document.createElement('button');
        this.button.id = 'quickActionsButton';
        this.button.className =
            'flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-primary text-white shadow-lg transition-all duration-200 hover:shadow-xl hover:scale-110 group';
        this.button.setAttribute('aria-label', 'Quick actions');
        this.button.innerHTML =
            '<i class="fas fa-bolt text-xl transition-transform duration-200 group-hover:rotate-12"></i>';
        if (mount) {
            mount.appendChild(this.wrap);
        } else {
            Object.assign(this.wrap.style, {
                position: 'fixed',
                right: '1.5rem',
                bottom: '1.5rem',
                zIndex: '40'
            });
            document.body.appendChild(this.wrap);
        }
        this.wrap.appendChild(this.button);
    }

    createMenu() {
        if (!this.wrap || !this.button) return;
        this.menu = document.createElement('div');
        this.menu.id = 'quickActionsMenu';
        this.menu.className =
            'fab-bolt-menu absolute bottom-full right-0 mb-2 flex min-w-[200px] flex-col gap-2';
        Object.assign(this.menu.style, {
            position: 'absolute',
            right: '0',
            bottom: 'calc(100% + var(--fab-menu-gap, 0.625rem))',
            display: 'none',
            flexDirection: 'column',
            gap: 'var(--fab-menu-gap, 0.625rem)',
            marginBottom: '0',
            minWidth: '200px',
            zIndex: '101'
        });
        let menuHTML = '';
        this.actions.forEach((action, index) => {
            menuHTML += `
                <button
                    data-action="${action.id}"
                    class="${action.color} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 transition-all duration-200 hover:scale-105 hover:shadow-xl min-w-[200px] group"
                    style="animation: slideInRight 0.3s ease-out ${index * 0.05}s both;"
                    title="${action.shortcut ? 'Shortcut: ' + action.shortcut : ''}"
                >
                    <i class="${action.icon} text-lg group-hover:scale-110 transition-transform"></i>
                    <span class="font-medium flex-1 text-left">${action.label}</span>
                    ${action.shortcut ? `<kbd class="text-xs opacity-75 bg-white/20 px-2 py-1 rounded">${action.shortcut}</kbd>` : ''}
                </button>
            `;
        });
        this.menu.innerHTML = menuHTML;
        this.wrap.insertBefore(this.menu, this.button);
        this.attachMenuActionListeners();

        if (!document.getElementById('quickActionsKeyframes')) {
            const style = document.createElement('style');
            style.id = 'quickActionsKeyframes';
            style.textContent = `
            @keyframes slideInRight {
                from { opacity: 0; transform: translateX(20px); }
                to { opacity: 1; transform: translateX(0); }
            }
            #quickActionsButton.open i {
                transform: rotate(45deg);
            }
            @media (max-width: 768px) {
                #quickActionsMenu button {
                    min-width: calc(100vw - 2rem);
                }
            }
        `;
            document.head.appendChild(style);
        }
    }

    attachButtonListener() {
        if (!this.button || this._buttonBound) return;
        this._buttonBound = true;
        this.button.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });
    }

    attachMenuActionListeners() {
        if (!this.menu) return;
        this.menu.querySelectorAll('[data-action]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const actionId = btn.dataset.action;
                const action = this.actions.find((a) => a.id === actionId);
                if (action) {
                    action.action();
                    this.close();
                }
            });
        });
    }

    attachGlobalListeners() {
        if (this._globalsBound) return;
        this._globalsBound = true;
        document.addEventListener('click', (e) => {
            if (
                this.isOpen &&
                this.wrap &&
                !this.wrap.contains(e.target)
            ) {
                this.close();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    open() {
        this.isOpen = true;
        if (this.menu) this.menu.style.display = 'flex';
        if (this.wrap) this.wrap.classList.add('is-open');
        if (this.mount) this.mount.classList.add('is-open');
        this.button.classList.add('open');
    }

    close() {
        this.isOpen = false;
        if (this.menu) this.menu.style.display = 'none';
        if (this.wrap) this.wrap.classList.remove('is-open');
        if (this.mount) this.mount.classList.remove('is-open');
        this.button.classList.remove('open');
    }

    startTimer() {
        const startBtn = document.querySelector(
            '#openStartTimer, button[onclick*="startTimer"]'
        );
        if (startBtn) {
            startBtn.click();
        } else {
            window.location.href = '/timer/manual_entry';
        }
    }

    addAction(action) {
        this.actions.push(action);
        this.recreateMenu();
    }

    removeAction(actionId) {
        this.actions = this.actions.filter((a) => a.id !== actionId);
        this.recreateMenu();
    }

    recreateMenu() {
        if (this.menu) {
            this.menu.remove();
            this.menu = null;
        }
        this.createMenu();
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.quickActionsMenu = new QuickActionsMenu();
});
