
/*@preserve
***Version 2.54.0***
*/

/*@license
 *                       Copyright 2002 - 2018 Qualtrics, LLC.
 *                                All rights reserved.
 *
 * Notice: All code, text, concepts, and other information herein (collectively, the
 * "Materials") are the sole property of Qualtrics, LLC, except to the extent
 * otherwise indicated. The Materials are proprietary to Qualtrics and are protected
 * under all applicable laws, including copyright, patent (as applicable), trade
 * secret, and contract law. Disclosure or reproduction of any Materials is strictly
 * prohibited without the express prior written consent of an authorized signatory
 * of Qualtrics. For disclosure requests, please contact notice@qualtrics.com.
 */

try {
  QSI.Link=QSI.util.Creative({initialize:function(i){this.globalInitialize(i),this.options.locators&&(QSI.PipedText.setLocators(this.options.locators),this.options.text=QSI.PipedText.evaluateLocators(this.options.text)),this.shouldShow()&&this.insertLink()},insertLink:function(){if(this.options.insertionLocation&&this.options.targetURL){var i=this.options.text||this.options.targetURL;this.link=QSI.util.build("a",{className:"QSILink "+this.id+"_Link",href:"javascript:void(0);"},i),new QSI.Target(this.link,this.getTargetHelper(),this.actionOptions,this),QSI.util.$(this.options.insertionLocation).appendChild(this.link),this.impress(),this.displayed.resolve()}},remove:function(){this.link&&QSI.util.remove(this.link)}});
} catch(e) {
  if (typeof QSI !== 'undefined' && QSI.dbg && QSI.dbg.e) {
    QSI.dbg.e(e);
  }
}