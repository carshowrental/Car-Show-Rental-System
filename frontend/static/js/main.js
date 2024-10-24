// main.js

document.addEventListener('DOMContentLoaded', function() {
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });



    // File input preview for license upload
    const licenseInput = document.getElementById('license_image');
    if (licenseInput) {
        licenseInput.addEventListener('change', previewLicense);
    }

    // Add fade-in animation to cards
    const cards = document.querySelectorAll('.card');
    cards.forEach(card => {
        card.classList.add('fade-in');
    });

    // Form validation
    const forms = document.querySelectorAll('.needs-validation');
    Array.from(forms).forEach(form => {
        form.addEventListener('submit', event => {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });






});



function previewLicense(event) {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.createElement('img');
            preview.src = e.target.result;
            preview.style.maxWidth = '100%';
            preview.style.marginTop = '10px';
            preview.classList.add('img-thumbnail');
            const container = document.getElementById('license_image').parentNode;
            if (container.querySelector('img')) {
                container.removeChild(container.querySelector('img'));
            }
            container.appendChild(preview);
        }
        reader.readAsDataURL(file);
    }
}