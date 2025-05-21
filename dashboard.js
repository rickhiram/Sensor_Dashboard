// Global variables
let charts = {};
let sensorData = {};
let currentProjectId = null;

const colors = {
    temperature: '#e74c3c',
    humidity: '#3498db',
    light: '#f1c40f',
    soil_moisture: '#2ecc71',
    distance: '#9b59b6',
    pressure: '#e67e22',
    co2: '#34495e',
    magnetic_field: '#8e44ad'
};

const units = {
    temperature: '°C',
    humidity: '%',
    light: 'lux',
    soil_moisture: '%',
    distance: 'cm',
    pressure: 'hPa',
    co2: 'ppm',
    magnetic_field: 'µT'
};

// Keep track of previous values for progressive lines
const previousValues = {};

function initChart(sensorId, sensorType) {
    const canvas = document.getElementById(`chart-${sensorId}`);
    if (!canvas) {
        console.error(`Canvas not found for sensor ${sensorId}`);
        return;
    }

    // Clean up existing chart if it exists
    if (charts[sensorId]) {
        charts[sensorId].destroy();
    }

    const ctx = canvas.getContext('2d');
    const unit = units[sensorType] || '';
    const color = colors[sensorType] || '#3498db';

    // Get appropriate min/max values and step size for each sensor type
    const ranges = {
        temperature: { min: 0, max: 40, step: 5, suffix: '°C' },
        humidity: { min: 0, max: 100, step: 10, suffix: '%' },
        light: { min: 0, max: 2000, step: 200, suffix: ' lux' },
        soil_moisture: { min: 0, max: 100, step: 10, suffix: '%' },
        distance: { min: 0, max: 200, step: 20, suffix: ' cm' },
        pressure: { min: 900, max: 1100, step: 20, suffix: ' hPa' },
        co2: { min: 400, max: 2000, step: 200, suffix: ' ppm' },
        magnetic_field: { min: 0, max: 100, step: 10, suffix: ' µT' }
    };

    const range = ranges[sensorType] || { min: 0, max: 100, step: 10, suffix: unit };

    charts[sensorId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: `${sensorType.replace('_', ' ').toUpperCase()}`,
                data: [],
                borderColor: color,
                backgroundColor: color + '20',
                borderWidth: 3,
                fill: true,
                tension: 0.4,
                pointRadius: 5,
                pointHoverRadius: 8,
                pointBackgroundColor: color
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 750,
                easing: 'easeInOutQuart'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        font: {
                            size: 14,
                            weight: 'bold'
                        },
                        padding: 15
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleFont: { size: 14 },
                    bodyFont: { size: 13 },
                    padding: 12,
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            return `Value: ${context.parsed.y}${range.suffix}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    min: range.min,
                    max: range.max,
                    ticks: {
                        stepSize: range.step,
                        callback: function(value) {
                            return value + range.suffix;
                        },
                        font: {
                            size: 12
                        }
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.1)',
                        drawBorder: false
                    },
                    title: {
                        display: true,
                        text: `${sensorType.replace('_', ' ').toUpperCase()} ${unit}`,
                        font: {
                            size: 14,
                            weight: 'bold'
                        },
                        padding: 15
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        maxRotation: 0,
                        font: {
                            size: 12
                        }
                    },
                    title: {
                        display: true,
                        text: 'Time',
                        font: {
                            size: 14,
                            weight: 'bold'
                        },
                        padding: 15
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        }
    });
}

function updateChart(sensorId, data) {
    if (!charts[sensorId]) return;

    const chart = charts[sensorId];

    // Format timestamps and values
    const labels = data.data.map(d => new Date(d[0]).toLocaleTimeString());
    const values = data.data.map(d => d[1]);

    // If this is the first update for this sensor, initialize previous values
    if (!previousValues[sensorId]) {
        previousValues[sensorId] = new Array(values.length).fill(null);
    }

    // Ensure arrays are the same length
    while (previousValues[sensorId].length < values.length) {
        previousValues[sensorId].push(null);
    }
    while (previousValues[sensorId].length > values.length) {
        previousValues[sensorId].pop();
    }

    // Create progressive animation
    const animationDuration = 1000; // 1 second
    const steps = 10;
    const stepDuration = animationDuration / steps;
    let currentStep = 0;

    function animateLines() {
        if (currentStep >= steps) {
            // Animation complete, save current values as previous
            previousValues[sensorId] = [...values];
            return;
        }

        const progress = (currentStep + 1) / steps;
        const currentValues = values.map((value, index) => {
            const prev = previousValues[sensorId][index];
            if (prev === null) return value;
            return prev + (value - prev) * progress;
        });

        chart.data.labels = labels;
        chart.data.datasets[0].data = currentValues;

        // Update chart options if needed
        if (data.unit) {
            chart.options.scales.y.title = {
                display: true,
                text: data.unit
            };
        }

        chart.update('none'); // Disable built-in animations for smoother custom animation
        currentStep++;
        setTimeout(animateLines, stepDuration);
    }

    // Start the animation
    animateLines();
}
