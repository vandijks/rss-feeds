##########################
### RSS Feed Generation ##
##########################

.PHONY: feeds_generate_all
feeds_generate_all: ## Generate all RSS feeds
	$(call check_venv)
	$(call print_info_section,Generating all RSS feeds)
	$(Q)python feed_generators/run_all_feeds.py
	$(call print_success,All feeds generated)

.PHONY: feeds_noordhollandsdagblad_alkmaar
feeds_noordhollandsdagblad_alkmaar: ## Generate RSS feed for Noordhollands Dagblad - Alkmaar
	$(call check_venv)
	$(call print_info,Generating Noordhollands Dagblad Alkmaar feed)
	$(Q)python feed_generators/noordhollandsdagblad_alkmaar.py
	$(call print_success,Noordhollands Dagblad Alkmaar feed generated)

.PHONY: clean_feeds
clean_feeds: ## Clean generated RSS feed files
	$(call print_warning,Removing generated RSS feeds)
	$(Q)rm -rf feeds/*.xml
	$(call print_success,RSS feeds removed)
