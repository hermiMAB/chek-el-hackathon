document.addEventListener('DOMContentLoaded', () => {
    // Check authentication status
    fetch('/api/check-auth')
      .then(response => response.json())
      .then(data => {
        if (!data.authenticated) {
          window.location.href = '/login';
        }
      })
      .catch(error => console.error('Error checking auth:', error));
  });