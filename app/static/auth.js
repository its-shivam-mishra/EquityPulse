
// --- Auth Logic ---

function initAuth() {
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    const showRegisterLink = document.getElementById("show-register");
    const showLoginLink = document.getElementById("show-login");
    const logoutBtn = document.getElementById("btn-logout");

    if (showRegisterLink && showLoginLink) {
        showRegisterLink.addEventListener("click", (e) => {
            e.preventDefault();
            loginForm.classList.add("hidden");
            registerForm.classList.remove("hidden");
        });

        showLoginLink.addEventListener("click", (e) => {
            e.preventDefault();
            registerForm.classList.add("hidden");
            loginForm.classList.remove("hidden");
        });
    }

    if (loginForm) {
        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = document.getElementById("login-username").value;
            const password = document.getElementById("login-password").value;
            try {
                const res = await fetch("/api/auth/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password })
                });
                if (!res.ok) {
                    const data = await res.json();
                    throw new Error(data.detail || "Login failed");
                }
                const data = await res.json();
                handleLoginSuccess(data.access_token);
            } catch (err) {
                showToast(err.message, "error");
            }
        });
    }

    if (registerForm) {
        registerForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = document.getElementById("register-username").value;
            const password = document.getElementById("register-password").value;
            try {
                const res = await fetch("/api/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password })
                });
                if (!res.ok) {
                    const data = await res.json();
                    throw new Error(data.detail || "Registration failed");
                }
                const data = await res.json();
                handleLoginSuccess(data.access_token);
            } catch (err) {
                showToast(err.message, "error");
            }
        });
    }

    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            handleLogout();
        });
    }
}

function handleLoginSuccess(token) {
    authToken = token;
    localStorage.setItem("auth_token", token);
    document.getElementById("auth-container").classList.add("hidden");
    document.getElementById("main-app").style.display = "block";
    showToast("Login successful", "success");
    initApp();
}

function handleLogout() {
    authToken = null;
    localStorage.removeItem("auth_token");
    document.getElementById("main-app").style.display = "none";
    document.getElementById("auth-container").classList.remove("hidden");
    
    // Clear forms
    const loginForm = document.getElementById("login-form");
    if(loginForm) loginForm.reset();
    const registerForm = document.getElementById("register-form");
    if(registerForm) registerForm.reset();
}
