// Toggling Sidebar Visibility and Icon
const sidebar = document.getElementById("sidebar");
const sidebarIconMain = document.getElementById("sidebarIconMain");
const sidebarIcon = document.getElementById("sidebarIcon");

function toggleSidebarVisibility(button, icon) {
  sidebar.classList.toggle("hidden");

  if (sidebar.classList.contains("hidden")) {
    icon.classList.remove("fa-times");
    icon.classList.add("fa-bars");
  } else {
    icon.classList.remove("fa-bars");
    icon.classList.add("fa-times");
  }
}

// Sidebar setup
sidebar.classList.remove("hidden");
sidebarIconMain.classList.add("fa-times");

document
  .getElementById("toggleSidebarMain")
  .addEventListener("click", function () {
    toggleSidebarVisibility(this, sidebarIconMain);
  });

document.getElementById("toggleSidebar").addEventListener("click", function () {
  toggleSidebarVisibility(this, sidebarIcon);
});

// Function to toggle dropdown visibility
function toggleDropdown(menuId, parentId = null) {
  const dropdownMenu = document.getElementById(menuId);

  // Hide other dropdowns except this one and its parent
  if (!parentId) {
    closeAllDropdownsExcept(menuId);
  }

  // Check if the dropdown menu is currently hidden
  if (dropdownMenu.classList.contains("hidden")) {
    // Show the dropdown by removing 'hidden' class
    dropdownMenu.classList.remove("hidden");
  } else {
    // Hide the dropdown by adding 'hidden' class
    dropdownMenu.classList.add("hidden");
  }
}

// Function to close all dropdowns except the currently opened one and its parent
function closeAllDropdownsExcept(menuId) {
  const dropdownMenus = document.querySelectorAll(".dropdown-menu");

  dropdownMenus.forEach((menu) => {
    // Only close dropdowns that are not the current one or not a parent
    if (menu.id !== menuId && !menu.classList.contains("hidden")) {
      menu.classList.add("hidden");
    }
  });
}

// Highlight active sidebar link on page load
document.addEventListener("DOMContentLoaded", function () {
  const currentPath = window.location.pathname;
  const sidebarLinks = document.querySelectorAll("#sidebar a");

  sidebarLinks.forEach((link) => {
    if (link.getAttribute("data-title") === "Home") {
      return;
    }

    if (link.href.endsWith(currentPath)) {
      link.classList.add("bg-cyan-800");

      const parentDropdownId = link.getAttribute("data-parent");

      // If the link has a parent dropdown, open the dropdown
      if (parentDropdownId) {
        const parentDropdown = document.getElementById(
          `dropdown${parentDropdownId}Menu`
        );
        if (parentDropdown) {
          parentDropdown.classList.remove("hidden");
        }
      }
    }
  });
});
