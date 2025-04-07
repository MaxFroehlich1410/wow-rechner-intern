from flask import Flask, render_template, request, send_file, Response, jsonify
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io
import base64
import tempfile
from functools import wraps
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg
import json

app = Flask(__name__)

USERNAME = "wowteam"
PASSWORD = "test1234"
latest_pdf_path = None

def check_auth(username, password):
    return username == USERNAME and password == PASSWORD

def authenticate():
    return Response("Login erforderlich", 401, {"WWW-Authenticate": 'Basic realm="WOW-Rechner Intern"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def format_currency(value):
    return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

def calculate_average_ticketpreis(kategorien, max_zuschauer):
    total_umsatz = 0.0
    total_plaetze = 0
    for kategorie in kategorien:
        anzahl_kategorie = int(kategorie['anzahl'])
        for stufe in kategorie.get('stufen', []):
            preis = float(stufe['preis'])
            anteil = float(stufe['anteil']) / 100
            anzahl = anzahl_kategorie * anteil
            total_plaetze += anzahl
            total_umsatz += anzahl * preis
    if total_plaetze == 0:
        return 0.0
    if round(total_plaetze) != int(max_zuschauer):
        raise ValueError(f"Summe aller Sitzplätze ({int(total_plaetze)}) stimmt nicht mit der Maximalanzahl ({max_zuschauer}) überein.")
    return total_umsatz / total_plaetze

def calculate_profit(MaxZuschauer, Showzahl, Tage, Tagesgage, SonstigeKosten, AverageTicketpreis, ShareDeal, Ticketanbieter_gebuehr, mit_ust):
    zuschauer = np.arange(0, Showzahl * MaxZuschauer + 1)
    if mit_ust:
        effektiver_preis = (AverageTicketpreis * 0.9 - Ticketanbieter_gebuehr) / 1.07
    else:
        effektiver_preis = AverageTicketpreis - AverageTicketpreis * 0.1 - Ticketanbieter_gebuehr
    gewinn = zuschauer * effektiver_preis * ShareDeal - (Tagesgage * Tage + SonstigeKosten)
    return zuschauer, gewinn

def generate_table(zuschauer, gewinn, max_people):
    break_even_index = np.abs(gewinn).argmin()
    break_even_zuschauer = zuschauer[break_even_index]
    break_even_prozent = round(100 * break_even_zuschauer / max_people)

    percent_steps = list(range(0, 101, 10))
    table_rows = []
    for percent in percent_steps:
        idx = int((percent / 100) * max_people)
        idx = min(idx, len(zuschauer) - 1)
        table_rows.append((int(zuschauer[idx]), f"{percent}%", format_currency(gewinn[idx])))

    be_row = (int(break_even_zuschauer), f"{break_even_prozent}% (Break-Even)", format_currency(gewinn[break_even_index]))
    table_rows.append(be_row)
    table_rows.sort(key=lambda row: row[0])
    return table_rows

@app.route('/', methods=['GET'])
@requires_auth
def index():
    return render_template('index.html')

    fig, ax = plt.subplots(figsize=(12, 6))
    # ... do the plot ...
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plot_url = base64.b64encode(buf.getvalue()).decode()
    plt.close()

    # store the raw PNG for PDF later
    global png_bytes
    png_bytes = buf.getvalue()

    return jsonify({
        "plot_url": plot_url,
        "table_data": table_data,
        "average_ticketpreis": round(float(data['average_ticketpreis']), 2)
        # note: no more "pdf_ready" needed
    })




@app.route('/calculate', methods=['POST'])
@requires_auth
def calculate():
    global png_bytes

    data = request.json

    # If we use ticket_kategorien, compute average price
    if data.get("use_ticket_kategorien"):
        kategorien = data.get("ticket_kategorien", [])
        try:
            data["average_ticketpreis"] = calculate_average_ticketpreis(kategorien, int(data['max_zuschauer']))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # Do normal calculation logic
    max_people = int(data['max_zuschauer']) * int(data['showzahl'])
    zuschauer, gewinn = calculate_profit(
        int(data['max_zuschauer']),
        int(data['showzahl']),
        int(data['tage']),
        float(data['tagesgage']),
        float(data['sonstige_kosten']),
        float(data['average_ticketpreis']),
        float(data['sharedeal']),
        float(data['Ticketanbieter_gebuehr']),
        data['mit_ust']
    )

    # Build the final table
    table_data = generate_table(zuschauer, gewinn, max_people)

    # Build a label_map for renamed inputs
    label_map = {
        "theater": "Theatername",
        "max_zuschauer": "Max. Zuschauer pro Show",
        "showzahl": "Anzahl Shows",
        "tage": "Anzahl Tage",
        "tagesgage": "Tagesgage",
        "sonstige_kosten": "Sonstige Kosten",
        "average_ticketpreis": "Durchschn. Ticketpreis",
        "sharedeal": "Share Deal Anteil",
        "Ticketanbieter_gebuehr": "Ticket Gebühren",
        "mit_ust": "Umsatzsteuer"
    }

    # lines[] for multiline text on plot
    lines = []
    for key in label_map:
        if key == "mit_ust":
            if data.get("mit_ust"):
                lines.append("Theater ist von Umsatzsteuer befreit")
            else:
                lines.append("Theater ist NICHT von Umsatzsteuer befreit")
        else:
            val = data.get(key, "")
            lines.append(f"{label_map[key]}: {val}")

    text_str = "\n".join(lines)

    # Now create the plot
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(zuschauer, gewinn, label='Gewinn')
    # Break-Even annotation
    break_even_index = np.abs(gewinn).argmin()
    break_even_zuschauer = zuschauer[break_even_index]
    break_even_prozent = round(100 * break_even_zuschauer / max_people)
    ax.axhline(0, color='green', linestyle='--', label='Break-Even')
    ax.annotate(
        f"{break_even_zuschauer} Zuschauer\n({break_even_prozent}%)",
        xy=(break_even_zuschauer, 0),
        xytext=(break_even_zuschauer, max(gewinn) * 0.6),
        arrowprops=dict(facecolor='red', arrowstyle="->"),
        fontsize=9, ha='center', color='red'
    )

    # Put the multiline user input text at upper-left
    ax.text(
        0.01, 0.99, text_str,
        transform=ax.transAxes,
        va='top',
        fontsize=9
    )

    ax.set_title(f"Gewinnprojektion – {data['theater']}")
    ax.set_xlabel("Zuschauer")
    ax.set_ylabel("Gewinn (€)")
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.legend()
    plt.tight_layout()

    # Save the plot as PNG to memory
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plot_url = base64.b64encode(buf.getvalue()).decode()
    plt.close(fig)

    # store the raw PNG for PDF
    png_bytes = buf.getvalue()

    return jsonify({
        "plot_url": plot_url,
        "table_data": table_data,
        "average_ticketpreis": round(float(data['average_ticketpreis']), 2)
    })



@app.route('/save-pdf', methods=['POST'])
@requires_auth
def save_pdf():
    global png_bytes

    data_json = request.form.get('data_json')
    table_data_json = request.form.get('table_data')
    if not data_json or not table_data_json:
        return "Fehlende Daten", 400

    data = json.loads(data_json)
    table_data = json.loads(table_data_json)

    # Provide nice labels for the input fields again
    label_map = {
        "theater": "Theatername",
        "max_zuschauer": "Max. Zuschauer pro Show",
        "showzahl": "Anzahl Shows",
        "tage": "Anzahl Tage",
        "tagesgage": "Tagesgage",
        "sonstige_kosten": "Sonstige Kosten",
        "average_ticketpreis": "Durchschn. Ticketpreis",
        "sharedeal": "Share Deal Anteil",
        "Ticketanbieter_gebuehr": "Ticket Gebühren",
        "mit_ust": "Umsatzsteuer",
        "use_ticket_kategorien": "Ticketkategorien genutzt"
    }

    # Build the final PDF
    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")

    with PdfPages(temp_pdf.name) as pdf:
        ##############################
        # Page 1: The Plot as image #
        ##############################
        fig1 = plt.figure(figsize=(8.27, 5))  # A4 wide, half tall
        ax1 = fig1.add_axes([0, 0, 1, 1])
        ax1.axis('off')

        # Re-construct the plot from the png_bytes
        img = mpimg.imread(io.BytesIO(png_bytes), format='png')
        ax1.imshow(img)
        pdf.savefig(fig1)
        plt.close(fig1)

        ##############################
        # Page 2: Inputs + Table    #
        ##############################
        fig2, ax2 = plt.subplots(figsize=(8.27, 11))  # A4 in portrait
        ax2.axis('off')

        # Title
        ax2.text(0.0, 0.97, "Eingegebene Werte:", fontsize=12, fontweight='bold', transform=ax2.transAxes)

        # Print the user’s inputs in nice format
        y_text = 0.92
        for key in label_map:
            if key == "mit_ust":
                is_on = data.get(key, False)
                val_str = "Theater ist von Umsatzsteuer befreit" if is_on else "Theater ist NICHT von Umsatzsteuer befreit"
                ax2.text(0.0, y_text, val_str, fontsize=10, transform=ax2.transAxes)
            else:
                val = data.get(key, "")
                ax2.text(0.0, y_text, f"{label_map[key]}: {val}", fontsize=10, transform=ax2.transAxes)
            y_text -= 0.04

        # table heading
        y_text -= 0.04
        ax2.text(0.0, y_text, "Ergebnistabelle:", fontsize=12, fontweight='bold', transform=ax2.transAxes)
        y_text -= 0.1

        from matplotlib.table import Table
        table_box = [0.0, 0.02, 1.0, y_text]  # from near bottom to y_text

        col_labels = ["Ticketanzahl", "Auslastung (%)", "Gewinn / Verlust (€)"]
        n_rows = len(table_data)+1  # +1 for header
        result_table = Table(ax2, bbox=table_box)

        # row 0 = header
        for col_idx, text in enumerate(col_labels):
            result_table.add_cell(
                0, col_idx, width=1/3, height=0.05,
                text=text, loc='center', facecolor='#dddddd'
            )

        # fill in rows
        for row_idx, row_data in enumerate(table_data):
            for col_idx, val in enumerate(row_data):
                result_table.add_cell(
                    row_idx+1, col_idx, width=1/3, height=0.05,
                    text=str(val), loc='center'
                )

        ax2.add_table(result_table)
        pdf.savefig(fig2)
        plt.close(fig2)

    return send_file(temp_pdf.name, as_attachment=True, download_name="gewinnanalyse.pdf")


if __name__ == '__main__':
    app.run(debug=True)
