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

    // Availability Check
    const availabilityForm = document.getElementById('availability-form');
    if (availabilityForm) {
        availabilityForm.addEventListener('submit', function(e) {
            e.preventDefault();
            checkCarAvailability();
        });
    }

    // Date Input Validation for car detail page
    const startDateInput = document.getElementById('start_date');
    const endDateInput = document.getElementById('end_date');
    if (startDateInput && endDateInput) {
        startDateInput.addEventListener('change', validateCarDates);
        endDateInput.addEventListener('change', validateCarDates);
    }

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

    // Contact form submission
    const contactForm = document.getElementById('contactForm');
    if (contactForm) {
        contactForm.addEventListener('submit', function(e) {
            e.preventDefault();
            // Add your AJAX submission logic here
            alert('Thank you for your message. We will get back to you soon!');
            contactForm.reset();
        });
    }

    // Smooth scrolling for rental policy page
    const policyLinks = document.querySelectorAll('.policy-nav a');
    policyLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            targetElement.scrollIntoView({ behavior: 'smooth' });
        });
    });

    // Car image carousel
    const carImageCarousel = document.getElementById('carImageCarousel');
    if (carImageCarousel) {
        const carousel = new bootstrap.Carousel(carImageCarousel);
        const thumbnails = document.querySelectorAll('.thumbnail-gallery img');
        thumbnails.forEach((thumb, index) => {
            thumb.addEventListener('click', () => {
                carousel.to(index);
                thumbnails.forEach(t => t.classList.remove('active'));
                thumb.classList.add('active');
            });
        });
    }
});

function checkCarAvailability() {
    const carId = document.querySelector('input[name="car_id"]').value;
    const startDate = document.getElementById('start_date').value;
    const endDate = document.getElementById('end_date').value;
    const policyAgreement = document.getElementById('policy_agreement').checked;

    if (!policyAgreement) {
        alert('You must agree to the rental policy to proceed.');
        return;
    }

    fetch(`/check-availability/?car_id=${carId}&start_date=${startDate}&end_date=${endDate}`)
        .then(response => response.json())
        .then(data => {
            const resultDiv = document.getElementById('availability-result');
            const bookingForm = document.getElementById('booking-form');
            resultDiv.style.display = 'block';
            if (data.available) {
                resultDiv.textContent = 'Car is available for the selected dates!';
                resultDiv.className = 'alert alert-success mt-3';
                bookingForm.style.display = 'block';
                document.getElementById('booking_start_date').value = startDate;
                document.getElementById('booking_end_date').value = endDate;
            } else {
                resultDiv.textContent = 'Car is not available for the selected dates. Please choose different dates.';
                resultDiv.className = 'alert alert-danger mt-3';
                bookingForm.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            const resultDiv = document.getElementById('availability-result');
            resultDiv.style.display = 'block';
            resultDiv.textContent = 'An error occurred while checking availability. Please try again.';
            resultDiv.className = 'alert alert-danger mt-3';
        });
}

function validateCarDates() {
    const startDate = new Date(document.getElementById('start_date').value);
    const endDate = new Date(document.getElementById('end_date').value);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (startDate < today) {
        alert('Start date cannot be in the past.');
        document.getElementById('start_date').value = '';
    }

    if (endDate < startDate) {
        alert('End date must be after the start date.');
        document.getElementById('end_date').value = '';
    }
}

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

function setActiveImage(index) {
    const carousel = document.getElementById('carImageCarousel');
    const carouselInstance = bootstrap.Carousel.getInstance(carousel);
    carouselInstance.to(index);

    const thumbnails = document.querySelectorAll('.thumbnail-gallery img');
    thumbnails.forEach((thumb, i) => {
        thumb.classList.toggle('active', i === index);
    });
}