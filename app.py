from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from tools.norma import NormaVisitata, Norma
from tools.xlm_htmlextractor import extract_html_article
from tools import pdfextractor, urngenerator, sys_op, brocardi
import os
import logging
from cachetools import TTLCache, cached

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s',
                    handlers=[logging.FileHandler("app.log"),
                              logging.StreamHandler()])

# Configure cache
norma_cache = TTLCache(maxsize=100, ttl=600)
article_cache = TTLCache(maxsize=100, ttl=600)
brocardi_cache = TTLCache(maxsize=100, ttl=600)
history=[]
app = Flask(__name__)

@app.route('/')
def home():
    """
    Renders the home page.
    """
    return render_template('index.html')

def convert_to_hashable(data):
    """
    Converts a dictionary to a hashable tuple.
    """
    return tuple(sorted(data.items()))

@cached(norma_cache, key=convert_to_hashable)
def create_norma_instance(data):
    act_type = data['act_type']
    date = data['date']
    act_number = data['act_number']
    article = data['article']
    version = data['version']
    version_date = data.get('version_date')  # Optional field

    normavisitata = NormaVisitata(
        norma=Norma(tipo_atto=act_type, data=date, numero_atto=act_number),
        numero_articolo=article,
        versione=version,
        data_versione=version_date
    )
    logging.info(f"Created NormaVisitata: {normavisitata}")
    return normavisitata

@app.route('/create_norma', methods=['POST'])
def create_norma():
    try:
        data = request.get_json()
        logging.info(f"Received data for create_norma: {data}")
        normavisitata = create_norma_instance(data)
        norma_data = normavisitata.to_dict()
        tree = normavisitata.tree

        # Append the NormaVisitata instance to history
        history.append(normavisitata)
        logging.info(f"Appended NormaVisitata to history. Current history size: {len(history)}")

        return jsonify({
            'norma_data': norma_data,
            'tree': tree,
            'urn': normavisitata.get_urn()
        })
    except Exception as e:
        logging.error(f"Error in create_norma: {e}", exc_info=True)
        return jsonify({'error': str(e)})

@cached(article_cache, key=lambda urn, article: (urn, article))
def extract_article_text(norma, article):
    normavisitata = NormaVisitata(
        norma=norma,
        numero_articolo=article,
        urn=norma.url
    )
    norma_art_text = extract_html_article(normavisitata) if article else ''
    logging.info(f"Extracted article text: {norma_art_text}")
    return norma_art_text

@app.route('/extract_article', methods=['POST'])
def extract_article():
    try:
        data = request.get_json()
        logging.info(f"Received data for extract_article: {data}")

        urn = data['urn']
        article = data['article']

        # Recupera l'istanza di Norma utilizzando l'URN
        norma = Norma(tipo_atto="costituzione", url=urn)  # Popola i campi appropriati di Norma

        norma_art_text = extract_article_text(norma, article)
        return jsonify({'result': norma_art_text})
    except Exception as e:
        logging.error(f"Error in extract_article: {e}", exc_info=True)
        return jsonify({'error': str(e)})

@cached(brocardi_cache, key=lambda urn: urn)
def get_brocardi_information(urn):
    norma = Norma(tipo_atto="costituzione", url=urn)  # Popola i campi appropriati di Norma
    normavisitata = NormaVisitata(
        norma=norma,
        urn=urn
    )
    brocardi_scraper = brocardi.BrocardiScraper()
    position, brocardi_info, brocardi_link = brocardi_scraper.get_info(normavisitata)
    return position, brocardi_info, brocardi_link

@app.route('/brocardi_info', methods=['POST'])
def brocardi_info():
    try:
        data = request.get_json()
        logging.info(f"Received data for brocardi_info: {data}")

        urn = data['urn']
        position, brocardi_info, brocardi_link = get_brocardi_information(urn)
        
        return jsonify({
            'brocardi_info': {
                'position': position,
                'info': brocardi_info,
                'link': brocardi_link
            } if position else None
        })
    except Exception as e:
        logging.error(f"Error in brocardi_info: {e}", exc_info=True)
        return jsonify({'error': str(e)})

@app.route('/history', methods=['GET'])
def get_history():
    try:
        logging.info("Fetching history")
        history_list = [norma.to_dict() for norma in history]
        return jsonify(history_list)
    except Exception as e:
        logging.error(f"Error in get_history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def downloaded_file(filename):
    return send_from_directory('download', filename)

@app.route('/export_pdf', methods=['POST'])
def export_pdf():
    try:
        data = request.get_json()
        urn = data['urn']
        logging.info(f"Received data for export_pdf: {urn}")

        filename = urngenerator.urn_to_filename(urn)
        
        if not filename:
            raise ValueError("Invalid URN")

        pdf_path = os.path.join(os.getcwd(), "download", filename)
        logging.info(f"PDF {filename} path: {pdf_path}")

        if not os.path.exists(pdf_path):
            # Setup or reuse the driver
            if not sys_op.drivers:
                driver = sys_op.setup_driver()
            else:
                driver = sys_op.drivers[0]

            pdf_path = pdfextractor.extract_pdf(driver, urn)
        
            if not pdf_path:
                raise ValueError("Error generating PDF")

            os.rename(os.path.join(os.getcwd(), "download", pdf_path), pdf_path)
            logging.info(f"PDF {filename} generated and saved: {pdf_path}")

        return jsonify({'pdf_url': url_for('downloaded_file', filename=filename)})
    except Exception as e:
        logging.error(f"Error in export_pdf: {e}", exc_info=True)
        return jsonify({'error': str(e)})
    finally:
        sys_op.close_driver()
        logging.info("Driver closed")

if __name__ == '__main__':
    logging.info("Starting Flask app in debug mode")
    app.run(debug=True)
