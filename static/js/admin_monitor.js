(() => {
  const raw = document.getElementById("admin-monitor-data");
  if (!raw || typeof Chart === "undefined") return;

  let data;
  try {
    data = JSON.parse(raw.textContent || "{}");
  } catch (_err) {
    return;
  }

  const ink = "#14233d";
  const muted = "#3e4f66";
  const blue = "#2a57d5";
  const indigo = "#5b3fd6";
  const green = "#157a59";
  const amber = "#b86a07";
  const soft = "#e8efff";

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: muted, boxWidth: 12, font: { family: "Inter, sans-serif", size: 12 } },
      },
    },
  };

  const hots = document.getElementById("chart-hots");
  if (hots && data.hots) {
    new Chart(hots, {
      type: "bar",
      data: {
        labels: data.hots.labels,
        datasets: [
          {
            label: "Good responses",
            data: data.hots.good,
            backgroundColor: [blue, indigo, green],
            borderRadius: 8,
            maxBarThickness: 42,
          },
        ],
      },
      options: {
        ...baseOptions,
        scales: {
          x: { ticks: { color: muted }, grid: { display: false } },
          y: {
            beginAtZero: true,
            ticks: { color: muted, precision: 0 },
            grid: { color: "rgba(20, 35, 61, 0.08)" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const subjects = document.getElementById("chart-subjects");
  if (subjects && data.subjects) {
    new Chart(subjects, {
      type: "bar",
      data: {
        labels: data.subjects.labels,
        datasets: [
          {
            label: "Average %",
            data: data.subjects.averages,
            backgroundColor: soft,
            borderColor: blue,
            borderWidth: 2,
            borderRadius: 8,
            maxBarThickness: 48,
          },
        ],
      },
      options: {
        ...baseOptions,
        scales: {
          x: { ticks: { color: muted }, grid: { display: false } },
          y: {
            beginAtZero: true,
            max: 100,
            ticks: { color: muted, callback: (v) => `${v}%` },
            grid: { color: "rgba(20, 35, 61, 0.08)" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const doughnutOptions = (chartData) => ({
    ...baseOptions,
    cutout: "62%",
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label(ctx) {
            const meanings = chartData.meanings || [];
            const percents = chartData.percents || [];
            const pct = percents[ctx.dataIndex];
            const meaning = meanings[ctx.dataIndex] || "";
            const count = ctx.raw;
            const studentWord = count === 1 ? "student" : "students";
            const bits = [`${ctx.label}: ${pct}% (${count} ${studentWord})`];
            if (meaning) bits.push(meaning);
            return bits;
          },
        },
      },
    },
  });

  const participation = document.getElementById("chart-participation");
  if (participation && data.participation) {
    new Chart(participation, {
      type: "doughnut",
      data: {
        labels: data.participation.labels,
        datasets: [
          {
            data: data.participation.values,
            backgroundColor: data.participation.colors || [green, "#c7d4e6"],
            borderWidth: 0,
          },
        ],
      },
      options: doughnutOptions(data.participation),
    });
  }

  const status = document.getElementById("chart-status");
  if (status && data.status) {
    new Chart(status, {
      type: "doughnut",
      data: {
        labels: data.status.labels,
        datasets: [
          {
            data: data.status.values,
            backgroundColor: data.status.colors || [green, blue, amber, "#c7d4e6"],
            borderWidth: 0,
          },
        ],
      },
      options: doughnutOptions(data.status),
    });
  }
})();
